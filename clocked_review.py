"""Local evidence reviewer backed by Clocked. No API key is sent to the browser."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_URL = "https://clocked.rezolve.ai/clocked/"
PUBLIC = Path(__file__).resolve().parent / "public"
MAX_BODY = 100_000
TIMEOUT = 25


class InputError(ValueError):
    pass


def validate(data):
    if not isinstance(data, dict):
        raise InputError("Request must be a JSON object.")
    question, answer, docs = data.get("question"), data.get("answer"), data.get("documents")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise InputError("Question must contain 1–4,000 characters.")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 20000:
        raise InputError("Answer must contain 1–20,000 characters.")
    if not isinstance(docs, list) or not 2 <= len(docs) <= 10:
        raise InputError("Provide between 2 and 10 source documents.")
    clean, seen = [], set()
    for doc in docs:
        if not isinstance(doc, dict):
            raise InputError("Each source must be an object.")
        ident, title, text = doc.get("id"), doc.get("title", ""), doc.get("text")
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 128 or ident in seen:
            raise InputError("Every source needs a unique non-empty ID of at most 128 characters.")
        if not isinstance(title, str) or len(title) > 500:
            raise InputError("Source titles must be at most 500 characters.")
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise InputError("Each source text must contain 1–20,000 characters.")
        seen.add(ident)
        clean.append({"id": ident, "title": title, "text": text})
    if sum(len(x["text"]) for x in clean) > 70000:
        raise InputError("Sources must total no more than 70,000 characters.")
    return question, answer, clean


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_clocked(endpoint, payload, key, opener=None):
    # Never forward the bearer token to a redirect target.
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect()).open
    req = urllib.request.Request(BASE_URL + endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Idempotency-Key": str(uuid.uuid4()), "Accept": "application/json"}, method="POST")
    try:
        with opener(req, timeout=TIMEOUT) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected object")
        required = {"rerank": "results", "compare": "pairs", "grounding": "claims"}[endpoint]
        if not isinstance(result.get(required), list):
            raise ValueError("Missing expected result")
        return result, None
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 403:
            return None, "Clocked rejected the API key or access."
        if e.code == 429:
            return None, "Clocked is rate-limiting or the free allowance is exhausted."
        return None, f"Clocked returned HTTP {e.code}."
    except (TimeoutError, socket.timeout):
        return None, "Clocked request timed out; no result was assumed."
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None, "Clocked could not be reached or returned an invalid response."


def review(data, key, caller=request_clocked):
    question, answer, docs = validate(data)
    if not key:
        raise InputError("CLOCKED_API_KEY is not configured on the server.")
    text_docs = [{"id": d["id"], "text": d["text"]} for d in docs]
    requests = {
        "rerank": {"query": question, "documents": docs},
        "compare": {"documents": text_docs, "evidence": "all"},
        # Keep all supplied sources, even if rerank says skip: otherwise a conflict can be hidden.
        "grounding": {"question": question, "answer": answer, "documents": text_docs, "evidence": "all"},
    }
    results, errors = {}, {}
    for name, payload in requests.items():
        result, error = caller(name, payload, key)
        results[name] = result
        if error:
            errors[name] = error
    return {**results, "errors": errors}


class Handler(BaseHTTPRequestHandler):
    server_version = "SourceCheck"
    def log_message(self, *_args):
        pass  # Do not log request content, credentials, or user sources.

    def safe_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.safe_host():
            return self.send_error(403)
        name = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        if name not in {"index.html", "app.js", "style.css"}:
            return self.send_error(404)
        file = PUBLIC / name
        if not file.is_file():
            return self.send_error(404)
        content = file.read_bytes()
        types = {"html": "text/html", "js": "text/javascript", "css": "text/css"}
        self.send_response(200)
        self.send_header("Content-Type", types[name.rsplit(".", 1)[1]] + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if not self.safe_host() or self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
            return self.send_json(403, {"error": "Requests must originate from this local app."})
        if self.path != "/api/review":
            return self.send_json(404, {"error": "Unknown endpoint."})
        if self.headers.get_content_type() != "application/json":
            return self.send_json(415, {"error": "Expected JSON."})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > MAX_BODY:
                raise InputError("Request is empty or too large.")
            data = json.loads(self.rfile.read(n))
            result = review(data, os.environ.get("CLOCKED_API_KEY", ""))
        except (ValueError, UnicodeDecodeError) as e:
            return self.send_json(400, {"error": str(e) if isinstance(e, InputError) else "Invalid JSON."})
        self.send_json(200, result)


def main():
    if not os.environ.get("CLOCKED_API_KEY"):
        print("Set CLOCKED_API_KEY in your environment before starting.")
        return
    port = int(os.environ.get("SOURCECHECK_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SourceCheck running at http://127.0.0.1:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
