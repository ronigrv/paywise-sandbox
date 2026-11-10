"""PayPal sandbox order primitives; never contacts a live PayPal endpoint."""
import base64
import json
import re
import urllib.error
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation

SANDBOX = 'https://api-m.sandbox.paypal.com'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def amount_usd(raw):
    if not isinstance(raw, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,3})\.[0-9]{2}', raw):
        raise ValueError('Amount must be USD with two decimal places, at most 9999.99.')
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError('Invalid amount.') from error
    if value <= 0:
        raise ValueError('Amount must be greater than zero.')
    return format(value, '.2f')

def _send(path, body, headers, opener=None):
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect()).open
    request = urllib.request.Request(SANDBOX + path, data=body, headers=headers, method='POST')
    with opener(request, timeout=20) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('PayPal response too large.')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid PayPal response.')
    return value

def token(client_id, client_secret, opener=None):
    if not client_id or not client_secret:
        raise ValueError('PayPal sandbox credentials are not configured.')
    basic = base64.b64encode((client_id + ':' + client_secret).encode()).decode('ascii')
    result = _send('/v1/oauth2/token', b'grant_type=client_credentials', {
        'Authorization': 'Basic ' + basic, 'Content-Type': 'application/x-www-form-urlencoded'
    }, opener)
    if not isinstance(result.get('access_token'), str):
        raise ValueError('PayPal did not return an access token.')
    return result['access_token']

def create_order(amount, client_id, client_secret, opener=None):
    value = amount_usd(amount)
    access_token = token(client_id, client_secret, opener)
    body = {'intent': 'CAPTURE', 'purchase_units': [{'amount': {'currency_code': 'USD', 'value': value}}]}
    order = _send('/v2/checkout/orders', json.dumps(body).encode(), {
        'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json',
        'PayPal-Request-Id': str(uuid.uuid4())
    }, opener)
    if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', str(order.get('id', ''))):
        raise ValueError('PayPal did not return a valid order ID.')
    return order['id']

def capture_order(order_id, client_id, client_secret, opener=None):
    if not isinstance(order_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', order_id):
        raise ValueError('Invalid order ID.')
    access_token = token(client_id, client_secret, opener)
    return _send('/v2/checkout/orders/' + order_id + '/capture', b'{}', {
        'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json',
        'PayPal-Request-Id': str(uuid.uuid4())
    }, opener)
