# Paywise

Paywise is a local experiment that compares a quote and an invoice with Clocked, then lets the reviewer choose a **PayPal sandbox** checkout. It uses synthetic example data and never connects to the live PayPal API. It does not detect fraud or guarantee that a transaction is safe. Review the originals yourself.

## Status

The fictional example was tested end to end with PayPal sandbox credentials and a simulated buyer: the app reported the sandbox order as COMPLETED. The AI comparison identified the differing revision terms and grounded the amount in the invoice. No real payment was made. PayPal order handling is also covered by mocked tests.

## Requirements and setup

Python 3.9+, a Clocked key and PayPal **sandbox** client ID and secret. PayPal's free developer dashboard supplies a sandbox app and simulated buyer. Do not commit secrets. The server binds only to localhost and never prints submitted documents or keys. Document text is transmitted to Clocked; use only data you are authorized to share.

PowerShell:

```powershell
$env:CLOCKED_API_KEY = 'your-clocked-key'
$env:PAYPAL_SANDBOX_CLIENT_ID = 'your-sandbox-client-id'
$env:PAYPAL_SANDBOX_SECRET = 'your-sandbox-secret'
python server.py
```

Open http://127.0.0.1:8766/. Use the fictional example or enter a quote and invoice. Review the comparison and amount evidence, acknowledge the limitations, and use a PayPal sandbox buyer if you choose to test checkout. Never use a real buyer or live client ID. The PayPal secret remains on the server; the public sandbox client ID is sent to the browser to initialize the SDK. Stop with Ctrl+C.

Clocked calls consume credits; check its current free allowance before running. Live access is not needed for the unit tests:

```powershell
python -m unittest -v
```

## How it works

- Clocked Compare examines the quote and invoice for relationships and possible conflicts. Grounding checks the selected payment amount against the invoice alone, so a quote cannot be mistaken for invoice evidence. Both results include evidence where the API returns it.
- The UI removes old results when inputs change and requires a fresh review before showing checkout. AI output does not authorize or control payment.
- The server creates and captures orders only at `api-m.sandbox.paypal.com`. It checks inputs, rejects redirects, and only accepts one capture attempt for an order this process created. A capture error may be ambiguous: check the sandbox dashboard before retrying. This is a demo, not a production payment system: it has no durable order store, authentication, webhook reconciliation or retry system.

Sources: [PayPal sandbox accounts](https://developer.paypal.com/tools/sandbox/accounts/), [PayPal Orders integration](https://developer.paypal.com/docs/checkout/standard/integrate/), [Clocked Compare](https://clocked.rezolve.ai/docs/compare), and [Clocked Grounding](https://clocked.rezolve.ai/docs/grounding).
