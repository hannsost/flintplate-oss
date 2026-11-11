// Host-only UI logic regressions. No browser, API or private fixtures are used.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../lib/flintplate-stations.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  fileName: "flintplate-stations.ts",
}).outputText;
const { stationTabs, lineStationName, readStationMutation, stationCommandForSend } = await import(
  `data:text/javascript,${encodeURIComponent(compiled)}`
);

const registry = [
  { code: "s_grill", name: "Grill umbenannt", kind: "kitchen", active: true, sort_order: 10 },
  { code: "bar", name: "Bar", kind: "bar", active: true, sort_order: 20 },
  { code: "s_cold", name: "Kaltküche", kind: "kitchen", active: false, sort_order: 30 },
  { code: "service", name: "Service", kind: "service", active: true, sort_order: 40 },
];
const line = (station, quantity, preparation_status = "sent", name = station) => ({
  kind: "product", station, quantity, preparation_status,
  station_snapshot: { id: station, code: station, name, kind: station === "bar" ? "bar" : "kitchen" },
});
const oldGrill = line("s_grill", 2, "preparing", "Grill bei Bestellung");
const orders = [{ status: "preparing", lines: [
  oldGrill, line("bar", 1), line("s_cold", 3), line("s_grill", 9, "served"),
] }, { status: "cancelled", lines: [line("s_grill", 99)] }];
assert.deepEqual(stationTabs(registry, orders), [
  { code: "all", label: "Alle Stationen", count: 6 },
  { code: "s_grill", label: "Grill umbenannt", count: 2 },
  { code: "bar", label: "Bar", count: 1 },
  { code: "s_cold", label: "Kaltküche · inaktiv", count: 3 },
]);
assert.equal(lineStationName(oldGrill), "Grill bei Bestellung");
assert.equal(lineStationName({ station: "kitchen" }), "Küche");
assert.equal(lineStationName({ station: "unknown" }), "Station nicht dokumentiert");
assert.ok(!stationTabs(registry, []).some(tab => tab.code === "s_cold"));
const orphan = stationTabs(registry, [{ status: "sent", lines: [line("s_orphan", 2, "sent", "Alte Station")] }]);
assert.deepEqual(orphan.find(tab => tab.code === "s_orphan"), { code: "s_orphan", label: "Alte Station", count: 2 });

const request_key = "12345678-1234-4234-8234-123456789abc";
const id = "22345678-1234-4234-8234-123456789abc";
const create = { kind: "create", body: { request_key, name: "Grill", sort_order: 50, kind: "kitchen" } };
assert.deepEqual(readStationMutation(JSON.stringify(create)), create);
assert.deepEqual(stationCommandForSend(JSON.stringify(create), { ...create, body: { ...create.body, name: "Geändertes Formular" } }), { command: create, retry: true });
assert.throws(() => stationCommandForSend(JSON.stringify(create), { ...create, body: { ...create.body, request_key: id } }));
const update = { kind: "update", id, body: { request_key, name: "Grill", sort_order: 50, version: 2, active: false } };
assert.deepEqual(readStationMutation(JSON.stringify({ ...update, body: { ...update.body, kind: "bar" } })), update);
assert.throws(() => readStationMutation(JSON.stringify({ ...update, id: "../../other-venue" })));
assert.throws(() => readStationMutation(JSON.stringify({ ...create, body: { ...create.body, kind: "invented" } })));
assert.throws(() => readStationMutation(JSON.stringify({ ...create, body: { ...create.body, request_key: "lost" } })));
console.log("Station filter, snapshot labels and pending-command validation passed.");

const corrected = structuredClone(orders); corrected[0].lines[0].line_id = "grill-line"; corrected[0].cancelled_units = [{ line_id: "grill-line", unit: 0 }];
assert.equal(stationTabs(registry, corrected).find(tab => tab.code === "s_grill").count, 1);
assert.equal(stationTabs(registry, corrected)[0].count, 5);
