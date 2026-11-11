import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

// Fast transport contract checks; no browser, API process or database involved.
const source = await fs.readFile(new URL('../lib/flintplate-order-feed.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
function loadWith(api) {
  const result = { exports: {} };
  vm.runInNewContext(compiled, { exports: result.exports, require: () => ({ venueApi: api }) });
  return result.exports.loadOrderFeed;
}
const order = (index, version = 1) => ({ id: `order-${String(index).padStart(6, '0')}`, created_at: '2026-09-12T12:00:00Z', version, status: 'served' });
const first = Array.from({ length: 500 }, (_, index) => order(index));
const calls = [];
const feed = loadWith(async (venue, path) => {
  calls.push({ venue, path });
  if (path.includes('include_closed')) return [...Array.from({ length: 99 }, (_, index) => ({ ...order(index + 1000), status: 'settled' })), order(500, 1)];
  return path.includes('before=') ? [order(500, 2)] : first;
});
const rows = await feed('venue-one');
assert.equal(rows.length, 600);
assert.equal(rows.find(row => row.id === order(500).id).version, 2);
assert.equal(calls[1].path, '/orders?limit=500&before=order-000499');
assert.equal(calls[2].path, '/orders?include_closed=true&limit=100');
assert.ok(calls.every(call => call.venue === 'venue-one'));
let kitchenCalls = 0;
const kitchen = loadWith(async (_venue, path) => { kitchenCalls++; assert.ok(!path.includes('include_closed')); return [order(42)]; });
assert.equal((await kitchen('venue-one', false)).length, 1);
assert.equal(kitchenCalls, 1);
const loop = loadWith(async () => first);
await assert.rejects(() => loop('venue-one'), /vollständige Bonliste/);
let pages = 0;
const oversized = loadWith(async () => Array.from({ length: 500 }, (_, index) => order(pages * 500 + index)).map((row, index) => { if (index === 499) pages++; return row; }));
await assert.rejects(() => oversized('venue-one'), /10\.000 aktive Bons/);
console.log('Order-feed contracts passed: active pagination, newest-version merge, kitchen scope, broken cursor, explicit 10,000-order boundary.');
