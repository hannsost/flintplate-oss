// Pure browser-side amount/quantity and cursor contracts. No API, DB or browser.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

async function module(name, api) {
  const text = await fs.readFile(new URL(`../lib/${name}.ts`, import.meta.url), 'utf8');
  const code = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  new Function('require', 'exports', code)(name => { assert.equal(name, './flintplate'); return { venueApi: api }; }, exports);
  return exports;
}
const projection = await module('flintplate-cancellations', () => { throw new Error('Unexpected API call'); });
const order = { total_cents: 2400, tip_cents: 200, lines: [{ line_id: 'dish', quantity: 3 }, { line_id: 'deposit', quantity: 1 }], cancelled_units: [{ line_id: 'dish', unit: 1, gross_cents: 700 }, { line_id: 'tip', unit: 0, gross_cents: 200 }] };
const snapshot = structuredClone(order);
assert.equal(projection.remainingOrderQuantity(order, 'dish'), 2);
assert.equal(projection.remainingOrderQuantity(order, 'deposit'), 1);
assert.equal(projection.cancelledOrderCents(order), 900);
assert.equal(projection.correctedOrderCents(order), 1700);
assert.deepEqual(order, snapshot, 'Original receipt is immutable; tip is counted exactly once.');
assert.deepEqual(projection.guestPaymentProposal(order, 500), {tipLocked:true, requestTip:200, receiptCents:1700}, 'A cancelled tip stays credited while the original tip is replayed unchanged.');
assert.deepEqual(projection.guestPaymentProposal({...order, total_cents:2000, tip_cents:0, cancelled_units:[{line_id:'dish',unit:0,gross_cents:1000}]}, 200), {tipLocked:true,requestTip:0,receiptCents:1000}, 'A 20€ receipt with a 10€ cancellation must display 10€, not 20€ plus a new tip.');
assert.deepEqual(projection.guestPaymentProposal({...order, cancelled_units:[]}, 100), {tipLocked:false,requestTip:100,receiptCents:2500}, 'A new tip replaces the old proposal instead of being counted twice.');
assert.deepEqual(projection.cancellationBlockers({ money: { blockers: ['Adapterabgleich offen', 42] } }), ['Adapterabgleich offen']);

const venue = 'test-venue';
const event = sequence => ({ sequence, venue_id: venue });
let result = { items: [event(3), event(8)], through_sequence: 10, next_after: 8, has_more: true };
const calls = [];
const history = await module('flintplate-history', async (...args) => { calls.push(args); return result; });
assert.equal((await history.auditPage(venue)).through_sequence, 10);
result = { items: [event(10)], through_sequence: 10, next_after: 10, has_more: false };
await history.auditPage(venue, 8, 10);
assert.match(calls[1][1], /after=8&limit=500&through=10$/);
result = { ...result, through_sequence: 11 };
await assert.rejects(history.auditPage(venue, 8, 10), /Endstand/);
result = { items: [event(8)], through_sequence: 10, next_after: 8, has_more: true };
await assert.rejects(history.auditPage(venue, 8, 10), /Journalfolge/);
result = { items: [{ ...event(10), venue_id: 'other-venue' }], through_sequence: 10, next_after: 10, has_more: false };
await assert.rejects(history.auditPage(venue, 8, 10), /Journalfolge/);
result = { items: [], through_sequence: 10, next_after: 8, has_more: true };
await assert.rejects(history.auditPage(venue, 8, 10), /Journalseite/);

const requests = Array.from({ length: 50 }, (_, index) => ({ id: `request-${index}` }));
let page = 0;
const paginated = await module('flintplate-cancellations', async (_venue, path) => { page++; if (page === 1) return requests; assert.match(path, /before=request-49/); return [{ id: 'older-request' }]; });
assert.equal((await paginated.cancellationPages(venue, '/orders/order/cancellations')).length, 51);
const broken = await module('flintplate-cancellations', async () => requests);
await assert.rejects(broken.cancellationPages(venue, '/cancellations/kitchen?unacknowledged=true'), /vollständige Stornohistorie/);
console.log('Cancellation unit/tip projection, complete request pages and fixed audit export boundaries passed.');
