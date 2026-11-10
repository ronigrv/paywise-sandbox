"""Local-only demo: compare an invoice to a quote, then use PayPal sandbox."""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from paypal_sandbox import create_order, capture_order, amount_usd
from clocked_review import request_clocked

PUBLIC = Path(__file__).resolve().parent / 'public'
MAX_BODY = 60000
orders = {}
orders_lock = Lock()

def review_invoice(data, caller=request_clocked):
    if not isinstance(data, dict): raise ValueError('Expected an object.')
    quote, invoice = data.get('quote'), data.get('invoice')
    if not isinstance(quote, str) or not isinstance(invoice, str) or not quote.strip() or not invoice.strip():
        raise ValueError('Enter both the original quote and the invoice.')
    if max(len(quote), len(invoice)) > 20000: raise ValueError('Each document is limited to 20,000 characters.')
    amount = amount_usd(data.get('amount'))
    key = os.environ.get('CLOCKED_API_KEY', '')
    if not key: raise ValueError('CLOCKED_API_KEY is not configured.')
    docs = [{'id': 'quote', 'text': quote.strip()}, {'id': 'invoice', 'text': invoice.strip()}]
    comparison, compare_error = caller('compare', {'documents': docs, 'evidence': 'all'}, key)
    grounding, ground_error = caller('grounding', {
        'question': 'Does the invoice specify the agreed amount and terms?',
        'answer': 'The invoice requests a payment of $' + amount + ' USD.',
        'documents': [docs[1]], 'evidence': 'all'
    }, key)
    return {'compare': comparison, 'grounding': grounding,
            'errors': {k: v for k, v in [('compare', compare_error), ('grounding', ground_error)] if v}}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def allowed(self): return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
    def respond(self, status, value):
        data = json.dumps(value).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if not self.allowed(): return self.send_error(403)
        if self.path == '/api/config':
            return self.respond(200, {'paypalClientId': os.environ.get('PAYPAL_SANDBOX_CLIENT_ID', '')})
        path = self.path.split('?', 1)[0].lstrip('/') or 'index.html'
        if path not in ('index.html', 'app.js', 'style.css'): return self.send_error(404)
        data = (PUBLIC / path).read_bytes()
        types = {'html':'text/html', 'js':'text/javascript', 'css':'text/css'}
        self.send_response(200); self.send_header('Content-Type', types[path.rsplit('.', 1)[1]] + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline' https://*.paypal.com https://*.paypalobjects.com; connect-src 'self' https://*.paypal.com; frame-src https://*.paypal.com; img-src 'self' data: https://*.paypal.com https://*.paypalobjects.com; style-src 'self' 'unsafe-inline' https://*.paypal.com; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        if not self.allowed() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
            return self.respond(403, {'error': 'Requests must come from the local app.'})
        if self.headers.get_content_type() != 'application/json': return self.respond(415, {'error':'Expected JSON.'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n < 1 or n > MAX_BODY: raise ValueError('Request too large or empty.')
            data = json.loads(self.rfile.read(n))
            if self.path == '/api/review': return self.respond(200, review_invoice(data))
            if self.path == '/api/orders':
                oid = create_order(data.get('amount'), os.environ.get('PAYPAL_SANDBOX_CLIENT_ID', ''), os.environ.get('PAYPAL_SANDBOX_SECRET', ''))
                with orders_lock: orders[oid] = 'created'
                return self.respond(200, {'id': oid})
            if self.path == '/api/capture':
                oid = data.get('id')
                with orders_lock:
                    if orders.get(oid) != 'created': raise ValueError('Order is unknown or already being handled.')
                    orders[oid] = 'capture-in-progress'
                try:
                    result = capture_order(oid, os.environ.get('PAYPAL_SANDBOX_CLIENT_ID', ''), os.environ.get('PAYPAL_SANDBOX_SECRET', ''))
                except Exception:
                    # A timeout can mean the provider processed the capture. Do not retry blindly.
                    with orders_lock: orders[oid] = 'capture-uncertain'
                    return self.respond(502, {'error':'Sandbox capture status is uncertain. Check the sandbox dashboard before trying again.'})
                with orders_lock: orders[oid] = 'captured' if result.get('status') == 'COMPLETED' else 'capture-uncertain'
                return self.respond(200, {'id': result.get('id'), 'status': result.get('status')})
            return self.respond(404, {'error':'Unknown endpoint.'})
        except (ValueError, TypeError, json.JSONDecodeError): return self.respond(400, {'error':'Check the inputs or service configuration.'})
        except Exception: return self.respond(502, {'error':'A test service was unavailable. No result was assumed.'})

if __name__ == '__main__':
    port = int(os.environ.get('PREFLIGHT_PORT', '8766'))
    print(f'Preflight running at http://127.0.0.1:{port}/ (PayPal sandbox only)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
