import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../lib/flintplate-purchase-preparation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { preparePurchaseEditor, readPurchaseEditor } = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);
const intent = { item_name: 'Mehl', source: { supplier_id: 'supplier', product_id: 'product', price_id: 'fixed-price-v3', supplier_terms_id: 'fixed-terms-v2', packs: 10, bonus_packs: 2, earliest_delivery_on: '2026-09-14' } };
const draft = preparePurchaseEditor(intent, 'draft-request-key');
assert.deepEqual(draft.packs, { product: '10' }); // Free packs never become paid packs.
assert.deepEqual(draft.price_ids, { product: 'fixed-price-v3' });
assert.equal(draft.supplier_terms_id, 'fixed-terms-v2');
assert.equal(draft.owner_id, ''); assert.equal(draft.location_id, '');
assert.equal(draft.expected_on, ''); // Planning assumptions do not become supplier promises.
assert.deepEqual(readPurchaseEditor(JSON.stringify(draft)), draft);
assert.equal(readPurchaseEditor(null), null);
assert.throws(() => preparePurchaseEditor({ ...intent, source: { ...intent.source, packs: null } }, 'key'));
assert.throws(() => readPurchaseEditor('{"key":"invalid"}'));
assert.throws(() => readPurchaseEditor(JSON.stringify({ ...draft, packs: { product: 10 } })));
console.log('Purchase preparation: paid packs and immutable source IDs preserved; owner/location explicit, incomplete drafts rejected.');
