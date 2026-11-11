import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

// Execute the real hook with a tiny deterministic React/storage host. The
// deferred read models the 201 -> authoritative GET window without a browser.
const source = await fs.readFile(new URL('../lib/flintplate-pending.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
class ApiError extends Error { constructor(status) { super(`HTTP ${status}`); this.status = status; } }
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function host(afterCommit) {
  const slots = [], effects = [], cleanups = [], values = new Map(), calls = [];
  let cursor = 0, user = { tenant_id: 'tenant', sub: 'manager' }, requestError;
  globalThis.window = new EventTarget();
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial }; },
    useEffect(effect) { const index = cursor++; if (!(index in slots)) { slots[index] = true; effects.push(effect); } },
  };
  const modules = {
    react, './flintplate-uuid': { newRequestId: () => crypto.randomUUID() }, './api': { ApiError }, './auth': { auth: { getUser: () => user } }, './flintplate-drafts': { AUTH_CHANGED_EVENT: 'auth-changed' },
    './flintplate': { message: cause => cause.message, venueApi: async (...args) => { calls.push(structuredClone(args)); if (requestError) throw requestError; return { version: 7 }; } },
  };
  const exports = {};
  new Function('require', 'exports', compiled)(name => { assert(name in modules, name); return modules[name]; }, exports);
  const render = () => { cursor = 0; return exports.useVenueMutation('venue', 'layout:', /^\/tables\/table\/position$/, afterCommit); };
  render(); for (const effect of effects) cleanups.push(effect());
  return { render, calls, values, error: value => { requestError = value; }, changeUser: () => { user = { tenant_id: 'tenant', sub: 'other-manager' }; window.dispatchEvent(new Event('auth-changed')); }, cleanup: () => cleanups.forEach(cleanup => cleanup?.()) };
}
const path = '/tables/table/position', payload = { version: 6, x: 240, y: 320 };
{
  const read = deferred(); let reads = 0;
  const h = host(() => { reads++; return read.promise; });
  const sending = h.render().send(path, payload, 'Tisch verschieben');
  await Promise.resolve();
  assert.equal(reads, 1); assert.equal(h.render().busy, true); assert.equal(h.values.size, 1); assert(h.render().pending);
  assert.equal(await h.render().send(path, { ...payload, x: 500 }, 'Weitere Änderung'), false);
  assert.equal(await h.render().retry(), false); assert.equal(h.calls.length, 1);
  read.resolve(); assert.equal(await sending, true);
  assert.equal(h.render().busy, false); assert.equal(h.render().pending, null); assert.equal(h.values.size, 0);
  h.cleanup();
}
{
  let failRead = true;
  const h = host(async () => { if (failRead) throw new ApiError(403); });
  assert.equal(await h.render().send(path, payload, 'Tisch verschieben'), false);
  assert(h.render().pending); assert.equal(h.values.size, 1); assert.equal(h.render().busy, false);
  const original = h.calls[0]; failRead = false;
  assert.equal(await h.render().retry(), true); assert.deepEqual(h.calls[1], original); assert.equal(h.values.size, 0);
  h.cleanup();
}
{
  const h = host(); h.error(new ApiError(409));
  assert.equal(await h.render().send(path, payload, 'Tisch verschieben'), false); assert.equal(h.render().pending, null); assert.equal(h.values.size, 0);
  h.error(new ApiError(503)); assert.equal(await h.render().send(path, payload, 'Tisch verschieben'), false); assert(h.render().pending); assert.equal(h.values.size, 1);
  h.cleanup();
}
{
  const read = deferred(), h = host(() => read.promise);
  const sending = h.render().send(path, payload, 'Tisch verschieben'); await Promise.resolve(); h.changeUser(); read.resolve();
  assert.equal(await sending, false); assert.equal(h.render().blocked, true); assert.equal(h.calls.length, 1);
  h.cleanup();
}
console.log('Layout pending: lock and durable request survive delayed reads; committed reads failing with 4xx retain exact retry; legacy rejection/503 and auth-change guards pass.');
