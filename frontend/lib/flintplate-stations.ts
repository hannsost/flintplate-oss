import type { Line, OperatingStation, Order, Station } from "./flintplate";

export const STATION_PENDING_PREFIX = "flintplate:station-pending:v1:";
export const STATION_FILTER_PREFIX = "flintplate:station-filter:v1:";
export const stationKindLabels: Record<Station, string> = {
  kitchen: "Küche", bar: "Bar", service: "Service", activities: "Aktivitäten",
};
export const preparationStation = (station: OperatingStation) =>
  station.kind === "kitchen" || station.kind === "bar";

/** Old bills retain the only two station labels supported before the upgrade. */
export function lineStationName(line: Line): string {
  if (line.station_snapshot) return line.station_snapshot.name;
  if (line.station === "kitchen") return "Küche";
  if (line.station === "bar") return "Bar";
  return "Station nicht dokumentiert";
}

export interface StationTab { code: string; label: string; count: number }

export function stationTabs(stations: OperatingStation[], orders: Order[]): StationTab[] {
  const counts = new Map<string, number>();
  const savedNames = new Map<string, string>();
  for (const order of orders) {
    if (["settled", "cancelled"].includes(order.status)) continue;
    for (const line of order.lines) {
      if (line.kind !== "product" || ["served", "cancelled"].includes(line.preparation_status)) continue;
      const remaining = Math.max(0, line.quantity - (order.cancelled_units ?? []).filter(unit => unit.line_id === line.line_id).length);
      if (!remaining) continue;
      counts.set(line.station, (counts.get(line.station) ?? 0) + remaining);
      savedNames.set(line.station, lineStationName(line));
    }
  }
  const rows = stations.filter(station => preparationStation(station) && (station.active || counts.has(station.code)))
    .slice().sort((left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name));
  const tabs = rows.map(station => ({
    code: station.code,
    label: station.name + (station.active ? "" : " · inaktiv"),
    count: counts.get(station.code) ?? 0,
  }));
  // A damaged/legacy record remains visible instead of silently leaving the KDS.
  const included = new Set(tabs.map(tab => tab.code));
  for (const [code, count] of counts) {
    if (!included.has(code)) tabs.push({ code, label: savedNames.get(code) ?? "Nicht zugeordnet", count });
  }
  return [{ code: "all", label: "Alle Stationen", count: [...counts.values()].reduce((sum, value) => sum + value, 0) }, ...tabs];
}

interface StationBaseCommand { request_key: string; name: string; sort_order: number }
export type StationMutation =
  | { kind: "create"; body: StationBaseCommand & { kind: Station } }
  | { kind: "update"; id: string; body: StationBaseCommand & { version: number; active: boolean } };

export function stationCommandForSend(raw: string | null, requested: StationMutation) {
  const saved = raw ? readStationMutation(raw) : null;
  if (saved && saved.body.request_key !== requested.body.request_key) {
    throw new Error("Eine andere Stationsänderung ist noch offen. Bitte zuerst diesen Vorgang prüfen.");
  }
  return { command: saved ?? requested, retry: saved !== null };
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);

export function readStationMutation(raw: string): StationMutation {
  let value: unknown;
  try { value = JSON.parse(raw); }
  catch { throw new Error("Gespeicherte Stationsänderung konnte nicht gelesen werden."); }
  if (!object(value) || !object(value.body)) throw new Error("Gespeicherte Stationsänderung ist unvollständig.");
  const data = value.body;
  if (!uuid(data.request_key) || typeof data.name !== "string" || data.name.trim().length < 2 || data.name.length > 80 || !Number.isInteger(data.sort_order) || Number(data.sort_order) < 0 || Number(data.sort_order) > 999) {
    throw new Error("Gespeicherte Stationsangaben konnten nicht sicher gelesen werden.");
  }
  const base = { request_key: data.request_key, name: data.name, sort_order: Number(data.sort_order) };
  if (value.kind === "create" && typeof data.kind === "string" && ["kitchen", "bar", "service", "activities"].includes(data.kind)) {
    return { kind: "create", body: { ...base, kind: data.kind as Station } };
  }
  if (value.kind === "update" && uuid(value.id) && Number.isInteger(data.version) && Number(data.version) > 0 && typeof data.active === "boolean") {
    return { kind: "update", id: value.id, body: { ...base, version: Number(data.version), active: data.active } };
  }
  throw new Error("Gespeicherter Stationsvorgang ist ungültig.");
}
