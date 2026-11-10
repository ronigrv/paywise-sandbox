'use strict';
const $ = selector => document.querySelector(selector);
const form = $('#form'), quote = $('#quote'), invoice = $('#invoice'), amount = $('#amount');
const status = $('#status'), findings = $('#findings'), ack = $('#ack'), paypalBox = $('#paypal');
let reviewAmount = '', paypalClient = '';
function message(text) { status.textContent = text; }
function clearReview() { findings.hidden = true; ack.checked = false; paypalBox.replaceChildren(); reviewAmount = ''; }
function addText(target, label, value) {
  const item = document.createElement('div'); item.className = 'result';
  const strong = document.createElement('strong'); strong.textContent = label; item.append(strong);
  const copy = document.createElement('span'); copy.textContent = value; item.append(copy); target.append(item);
}
function reset() {
  clearReview();
  quote.value = 'Fictional quote: Oak Studio will design one logo for $48.25 USD. Two revisions are included. Delivery is due within 10 days.';
  invoice.value = 'Fictional invoice: Logo design $48.25 USD. One revision is included. Delivery within 10 days.';
  amount.value = '48.25'; message('Example loaded. Review the two documents before deciding.');
}
async function api(path, payload) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request failed.');
  return result;
}
function showComparison(result) {
  const target = $('#comparison'); target.replaceChildren();
  const pairs = result && Array.isArray(result.pairs) ? result.pairs : [];
  if (!pairs.length) return addText(target, 'No comparison returned', 'Check both documents yourself.');
  pairs.forEach(pair => {
    const conflicts = Array.isArray(pair.conflicts) ? pair.conflicts : [];
    addText(target, 'Relationship: ' + String(pair.relation || 'not provided'), conflicts.length ? 'Review the conflict evidence below.' : 'No conflict evidence returned. This does not prove agreement.');
    conflicts.forEach(conflict => {
      const pieces = [conflict.description, conflict.a?.quote, conflict.b?.quote].filter(x => typeof x === 'string' && x);
      if (pieces.length) addText(target, 'Potential conflict', pieces.join(' / '));
    });
  });
}
function showGrounding(result) {
  const target = $('#grounding'); target.replaceChildren();
  const claims = result && Array.isArray(result.claims) ? result.claims : [];
  if (!claims.length) return addText(target, 'No amount result', 'Check the invoice amount yourself.');
  claims.forEach(claim => {
    const evidence = claim.evidence && typeof claim.evidence === 'object' ? claim.evidence : null;
    const source = evidence?.document || claim.source;
    const attribution = source ? ' [' + String(source) + ']' : '';
    addText(target, String(claim.verdict || 'Not provided').toUpperCase(),
      String(claim.claim || '') + (evidence?.quote ? ' — ' + evidence.quote + attribution : ' — No source quote returned.'));
  });
}
form.addEventListener('input', () => { if (!findings.hidden) {clearReview(); message('Details changed. Review them again before proceeding.');} });
$('#reset').addEventListener('click', reset);
form.addEventListener('submit', async event => {
  event.preventDefault(); clearReview();
  for (const item of form.querySelectorAll('button,input,textarea')) item.disabled = true;
  message('Reviewing both documents…');
  try {
    const reviewedAmount = amount.value.trim();
    const data = await api('/api/review', {quote:quote.value, invoice:invoice.value, amount:reviewedAmount});
    if (Object.keys(data.errors || {}).length) throw new Error('The review did not finish. Check the source documents and try again.');
    showComparison(data.compare); showGrounding(data.grounding); reviewAmount = reviewedAmount;
    findings.hidden = false; message('Review complete. Read the original documents and verify the result.');
  } catch (error) { message(error.message || 'Review unavailable.'); }
  finally { for (const item of form.querySelectorAll('button,input,textarea')) item.disabled = false; }
});
ack.addEventListener('change', async () => {
  paypalBox.replaceChildren();
  if (!ack.checked || !reviewAmount) return;
  if (!paypalClient || !window.paywiseSandbox) { message('PayPal sandbox is not configured or could not load.'); return; }
  try {
    await window.paywiseSandbox.Buttons({
      createOrder: async () => (await api('/api/orders', {amount:reviewAmount})).id,
      onApprove: async data => {
        const result = await api('/api/capture', {id:data.orderID});
        message('Sandbox order status: ' + String(result.status || 'unknown') + '. No real payment was made.');
        ack.checked = false; paypalBox.replaceChildren();
      },
      onCancel: () => message('Sandbox checkout cancelled.'),
      onError: () => message('Sandbox checkout did not complete or its status is uncertain. Check the PayPal sandbox dashboard before retrying.')
    }).render('#paypal');
  } catch (_) { message('Sandbox checkout could not load.'); }
});
async function init() {
  reset();
  try {
    const config = await (await fetch('/api/config')).json();
    paypalClient = config.paypalClientId || '';
    if (!paypalClient) { $('#checkout-note').textContent = 'To enable sandbox checkout, configure a PayPal sandbox client ID and secret on the server.'; return; }
    const script = document.createElement('script');
    script.dataset.namespace = 'paywiseSandbox';
    script.src = 'https://www.paypal.com/sdk/js?client-id=' + encodeURIComponent(paypalClient) + '&currency=USD&intent=capture';
    script.onerror = () => message('PayPal sandbox checkout could not load.');
    document.head.append(script);
  } catch (_) { message('Could not load demo configuration.'); }
}
init();
