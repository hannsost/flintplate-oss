// Pure UI contracts: no server, browser, real storage or database writes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { webcrypto } from 'node:crypto';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../lib');
const modules = new Map();
let user = { tenant_id: 'tenant-a', sub: 'service@example.test' };
const store = new Map();
globalThis.localStorage = { get length() { return store.size; }, key(index) { return [...store.keys()][index] ?? null; }, getItem(key) { return store.get(key) ?? null; }, setItem(key, value) { store.set(key, String(value)); }, removeItem(key) { store.delete(key); } };
if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: webcrypto });
function load(name) {
  if (name === 'react') return {};
  if (name === './auth') return { auth: { getUser: () => user } };
  if (modules.has(name)) return modules.get(name);
  const exports = {}; modules.set(name, exports);
  const source = fs.readFileSync(path.join(root, `${name.replace(/^\.\//, '')}.ts`), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  new Function('exports', 'require', code)(exports, load);
  return exports;
}
const rounds = load('./flintplate-rounds'), drafts = load('./flintplate-drafts'), undo = load('./flintplate-order-undo');
const payments = load('./flintplate-payments'), visits = load('./flintplate-visits'), recovery = load('./flintplate-round-pending');
const cashRecovery = load('./flintplate-cash-recovery');
const settledRecovery = { group: false, legacy: false, unavailable: false };
for (const [initial, pending, expected] of [
  ['guests', { ...settledRecovery, legacy: true }, 'single'],
  ['single', { ...settledRecovery, group: true }, 'guests'],
]) {
  const restored = cashRecovery.cashViewForRecovery(initial, pending);
  assert.equal(restored, expected);
  assert.equal(cashRecovery.cashViewForRecovery(restored, settledRecovery), expected, 'The source and confirmed refund/payment stay visible after a successful retry.');
  assert.equal(cashRecovery.cashViewForRecovery(initial, settledRecovery), initial, 'An explicit later tab choice still works after completion.');
  assert.equal(cashRecovery.cashViewForRecovery(restored, { ...settledRecovery, unavailable: true }), expected, 'A failed storage read cannot select a different source.');
}

// Regression for the real duplicate-sibling-key failure when changing visits:
// inspect the actual JSX keys, so a second stale composer cannot share identity
// with the neighbouring history component during reconciliation.
const visitSource = ts.createSourceFile('visits.tsx', fs.readFileSync(path.join(root, '../components/flintplate/visits.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const siblingKeys = new Map();
function collectVisitKeys(node) {
  if (ts.isJsxSelfClosingElement(node) && ['OrderComposer', 'VisitHistory'].includes(node.tagName.getText(visitSource))) {
    const key = node.attributes.properties.find(attribute => ts.isJsxAttribute(attribute) && attribute.name.getText(visitSource) === 'key');
    assert.ok(key?.initializer && ts.isJsxExpression(key.initializer) && key.initializer.expression);
    siblingKeys.set(node.tagName.getText(visitSource), new Function('visit', `return (${key.initializer.expression.getText(visitSource)});`));
  }
  ts.forEachChild(node, collectVisitKeys);
}
collectVisitKeys(visitSource);
assert.equal(siblingKeys.size, 2);
for (const id of ['visit-before', 'visit-after']) assert.notEqual(siblingKeys.get('OrderComposer')({ id }), siblingKeys.get('VisitHistory')({ id }), 'Composer and history must have distinct sibling identities.');
for (const key of siblingKeys.values()) assert.notEqual(key({ id: 'visit-before' }), key({ id: 'visit-after' }), 'Changing the visit must replace its prior component instance.');
const item = { id: 'menu-water', name: 'Wasser', version: 7, price_cents: 300, available: true };
let cart = rounds.changeRoundQuantity([], item, 'gast-a', 1, 'row-a');
cart = rounds.changeRoundQuantity(cart, item, 'gast-b', 1, 'row-b');
cart = rounds.changeRoundQuantity(cart, item, 'gast-a', 1, 'unused-row');
assert.deepEqual(cart.map(row => [row.rowId, row.guestTabId, row.quantity]), [['row-a', 'gast-a', 2], ['row-b', 'gast-b', 1]]);
cart[0].course = 2; cart[0].note = 'ohne Eis';
const rows = rounds.roundRows(cart);
assert.deepEqual(rows[0].assignments, [{ guest_tab_id: 'gast-a', units: [0, 1] }]);
assert.deepEqual(rows[1].assignments, [{ guest_tab_id: 'gast-b', units: [0] }]);
assert.equal(rows[0].course, 2); assert.equal(rows[0].note, 'ohne Eis');
assert.equal(rounds.matchesRoundRows(cart, structuredClone(rows)), true);
const altered = structuredClone(rows); altered[0].assignments[0].guest_tab_id = 'gast-b';
assert.equal(rounds.matchesRoundRows(cart, altered), false, 'A stored uncertain command cannot silently move items to another guest.');
assert.throws(() => rounds.roundRows([cart[0], cart[0]]), /unvollständig/);

const endpoint = '/gastro/venues/venue-a/service-visits/visit-a/rounds';
const scope = drafts.orderDraftScope(user, endpoint), target = { table: 'table-one', fulfillment: 'dine_in', visitId: 'visit-a' };
assert.equal(drafts.orderDraftKey(scope, target), drafts.orderDraftKey(scope, { ...target, table: 'table-two' }), 'The guest location is not the round identity.');
const before = drafts.emptyOrderDraft(target), after = { ...before, revision: 'edited', cart };
const history = undo.recordOrderUndo(undo.emptyOrderUndo(), drafts.orderDraftKey(scope, target), before, after, 'Runde erfasst');
assert.deepEqual(undo.orderUndoContent(history, drafts.orderDraftKey(scope, { ...target, table: 'table-two' }), after, 'edited'), { cart: [], note: '' });
assert.equal(undo.orderUndoContent(history, drafts.orderDraftKey(scope, { ...target, visitId: 'visit-b' }), after, 'edited'), null);
const command = { request_key: after.requestKey, visit_version: 4, tab_versions: [{ guest_tab_id: 'gast-a', version: 2 }, { guest_tab_id: 'gast-b', version: 1 }], fulfillment: 'dine_in', note: '', rows };
const pending = { ...after, pending: command, uncertain: true };
drafts.writeOrderDraft(scope, pending);
assert.deepEqual(drafts.readOrderDraft(scope, { ...target, table: 'table-two' }).pending, command);
assert.equal(undo.orderUndoContent(history, drafts.orderDraftKey(scope, target), pending, 'edited'), null);
assert.deepEqual(recovery.pendingRounds('venue-a'), [{ visitId: 'visit-a' }]);
assert.deepEqual(recovery.pendingRounds('venue-b'), []);
user = { ...user, sub: 'other@example.test' };
assert.deepEqual(recovery.pendingRounds('venue-a'), []);
user = { ...user, sub: 'service@example.test' };
store.set(drafts.orderDraftKey(scope, target), JSON.stringify({ ...pending, cart: [cart[1]] }));
assert.throws(() => drafts.readOrderDraft(scope, target), /passt nicht/);
store.set(drafts.orderDraftKey(scope, target), JSON.stringify({ ...pending, pending: { ...command, tab_versions: [{ guest_tab_id: 'gast-a', version: 2 }, { guest_tab_id: 'gast-a', version: 1 }] } }));
assert.throws(() => drafts.readOrderDraft(scope, target), /passt nicht/, 'Every involved guest requires exactly their own immutable version.');

const legacyScope = drafts.orderDraftScope(user, '/gastro/venues/venue-a/orders');
const old = drafts.emptyOrderDraft({ table: 'table-one', fulfillment: 'dine_in' });
old.cart = [{ item, quantity: 1 }]; old.uncertain = true;
old.pending = { request_key: old.requestKey, table_id: 'table-one', fulfillment: 'dine_in', guests: 1, note: '', lines: [{ item_id: item.id, menu_version: 7, quantity: 1, course: 1, note: '' }] };
drafts.writeOrderDraft(legacyScope, old);
assert.deepEqual(drafts.readOrderDraft(legacyScope, old), old, 'Legacy uncertain payloads remain byte-for-byte representable.');
assert.notEqual(drafts.orderDraftKey(legacyScope, old), drafts.orderDraftKey(scope, target));

for (const [input, expected] of [['0,01', 1], ['10.01', 1001], ['12,9', 1290], [' 0 ', 0], ['1.', 100]]) assert.equal(payments.euroCents(input), expected);
for (const invalid of ['1.001', '-1', 'Infinity', 'NaN', '1e2', '', '1,2,3', '1.000,00']) assert.equal(payments.euroCents(invalid), null);
assert.equal(payments.euroInput(1001), '10.01');
const bottle = { order_id: 'shared-order', line_id: 'bottle-line', unit: 0, name: 'Flasche', kind: 'product', guest_tab_id: 'shared', gross_cents: 1001, paid_cents: 0, remaining_cents: 1001, cancelled: false };
const water = { ...bottle, order_id: 'guest-order', line_id: 'water-line', guest_tab_id: 'gast-b', name: 'Wasser', remaining_cents: 300 };
const selected = payments.selectedUnitAmounts([bottle, water], { [payments.paymentUnitKey(bottle)]: '5.01' });
assert.deepEqual(selected, [{ order_id: 'shared-order', line_id: 'bottle-line', unit: 0, amount_cents: 501 }]);
assert.equal(bottle.gross_cents, 1001); assert.equal(bottle.unit, 0);
assert.throws(() => payments.selectedUnitAmounts([{ ...bottle, remaining_cents: 500 }], { [payments.paymentUnitKey(bottle)]: '5.01' }), /offenen Rests/);
assert.throws(() => payments.selectedUnitAmounts([{ ...bottle, cancelled: true }], { [payments.paymentUnitKey(bottle)]: '' }), /offenen Rests/);
assert.deepEqual(payments.selectedUnitAmounts([{ ...bottle, remaining_cents: 500 }], { [payments.paymentUnitKey(bottle)]: '' }), [{ order_id: 'shared-order', line_id: 'bottle-line', unit: 0 }], 'Whole-rest selection leaves the server authoritative; no stale original amount is posted.');
assert.equal(payments.groupPaymentUnits([bottle, { ...bottle, guest_tab_id: 'gast-a' }, water]).length, 3);
const partSelection = { mode: 'parts', part_ids: ['part-a2', 'part-a3'] };
assert.equal(payments.planMatchesPayment(partSelection, { parts: [{ id: 'part-b2' }, { id: 'part-b3' }] }), false, 'A remembered navigation context cannot identify another visit’s pending payment.');
assert.equal(payments.planMatchesPayment(partSelection, { parts: [{ id: 'part-a1' }, { id: 'part-a2' }, { id: 'part-a3' }] }), true);
assert.equal(payments.planMatchesPayment({ ...partSelection, part_ids: ['part-a2', 'part-a2'] }, { parts: [{ id: 'part-a2' }] }), false);

const order = { lines: [{ line_id: 'line-a', kind: 'product', quantity: 2 }], cancelled_units: [] };
assert.equal(visits.usesOriginalTable(order), true);
assert.equal(visits.usesOriginalTable(order, { round_id: 'round', assignments: [] }), false);
assert.equal(visits.usesOriginalTable(order, { round_id: null, assignments: [{ line_id: 'line-a', unit: 0 }] }), true);
assert.equal(visits.usesOriginalTable({ ...order, cancelled_units: [{ line_id: 'line-a', unit: 1 }] }, { round_id: null, assignments: [{ line_id: 'line-a', unit: 0 }] }), false);
for (const prefix of ['flintplate:payment-group-pending:v1:', 'flintplate:visit-pending:v1:', 'flintplate:payment-context:v1:', 'flintplate:split-context:v1:', 'flintplate:service-context:v1:']) store.set(prefix + 'private', '{}');
store.set('unrelated', 'preserve'); drafts.clearOrderDrafts(); assert.deepEqual([...store.keys()], ['unrelated']);
console.log('Guest UI: distinct rows, immutable round recovery, principal/visit/legacy isolation, undo across guest locations, exact financial fractions, presence and logout checks passed.');
