import io
import json
import unittest
import threading
import urllib.error
import urllib.request
from paypal_sandbox import amount_usd, capture_order, create_order
from server import review_invoice, Handler, ThreadingHTTPServer, orders
from unittest.mock import patch

class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

class SandboxTests(unittest.TestCase):
    def test_amount_rejects_invalid_and_zero(self):
        for value in ('0.00', '-1.00', '1', '1.000', '10000.00', '1e2', 1):
            with self.subTest(value=value), self.assertRaises(ValueError): amount_usd(value)
        self.assertEqual(amount_usd('48.25'), '48.25')

    def test_create_uses_sandbox_and_verified_amount(self):
        calls = []
        def open_fake(req, timeout):
            calls.append(req)
            response = {'access_token': 'example'} if req.full_url.endswith('/v1/oauth2/token') else {'id': 'ORDER-1'}
            return FakeResponse(json.dumps(response).encode())
        self.assertEqual(create_order('48.25', 'id', 'secret', open_fake), 'ORDER-1')
        self.assertTrue(all(r.full_url.startswith('https://api-m.sandbox.paypal.com/') for r in calls))
        self.assertEqual(json.loads(calls[1].data)['purchase_units'][0]['amount'], {'currency_code':'USD', 'value':'48.25'})

    def test_capture_rejects_path_injection_before_network(self):
        def no_network(*args, **kwargs): self.fail('invalid ID reached network')
        with self.assertRaises(ValueError): capture_order('../other', 'id', 'secret', no_network)

    def test_review_checks_both_documents_and_displays_errors(self):
        calls = []
        def caller(endpoint, payload, key):
            calls.append((endpoint, payload, key))
            return (None, 'Unavailable') if endpoint == 'compare' else ({'claims': []}, None)
        with patch.dict('os.environ', {'CLOCKED_API_KEY': 'test'}):
            result = review_invoice({'quote':'Quote text', 'invoice':'Invoice text', 'amount':'48.25'}, caller)
        self.assertEqual(result['errors'], {'compare':'Unavailable'})
        self.assertEqual([item['id'] for item in calls[0][1]['documents']], ['quote', 'invoice'])
        self.assertEqual([item['id'] for item in calls[1][1]['documents']], ['invoice'])
        self.assertIn('$48.25', calls[1][1]['answer'])

    def test_review_does_not_call_api_for_invalid_amount(self):
        def no_network(*args): self.fail('invalid input reached network')
        with patch.dict('os.environ', {'CLOCKED_API_KEY':'test'}), self.assertRaises(ValueError):
            review_invoice({'quote':'Quote', 'invoice':'Invoice', 'amount':'0.00'}, no_network)

    def test_ambiguous_capture_is_not_retried(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        orders['TEST-ORDER'] = 'created'
        def request():
            req = urllib.request.Request(origin + '/api/capture', data=b'{"id":"TEST-ORDER"}',
                headers={'Content-Type':'application/json', 'Origin':origin}, method='POST')
            try:
                with urllib.request.urlopen(req) as response: return response.status, json.load(response)
            except urllib.error.HTTPError as error: return error.code, json.load(error)
        try:
            with patch('server.capture_order', side_effect=TimeoutError()) as capture:
                first, result = request()
                second, _ = request()
                self.assertEqual(first, 502); self.assertIn('uncertain', result['error'])
                self.assertEqual(second, 400); self.assertEqual(capture.call_count, 1)
        finally:
            server.shutdown(); server.server_close(); worker.join(); orders.clear()

if __name__ == '__main__': unittest.main()
