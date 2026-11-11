import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import ts from 'typescript';
const source = await fs.readFile(new URL('../lib/flintplate-uuid.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
function withCrypto(crypto) { const sandbox = { crypto, exports: {} }; vm.runInNewContext(compiled, sandbox); return sandbox.exports.newRequestId; }
const lan = withCrypto({ getRandomValues: bytes => webcrypto.getRandomValues(bytes) });
const ids = Array.from({ length: 1000 }, () => lan());
assert.equal(new Set(ids).size, ids.length);
for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
assert.equal(withCrypto({ getRandomValues: bytes => bytes.fill(0) })(), '00000000-0000-4000-8000-000000000000');
assert.equal(withCrypto({ randomUUID: () => 'native-value', getRandomValues: () => { throw Error('Unexpected fallback'); } })(), 'native-value');
assert.throws(withCrypto(undefined), /sicheren Vorgangsschlüssel/);
console.log('UUID: native path, LAN CSPRNG fallback, RFC version/variant bits, uniqueness and unavailable-crypto failure pass.');
