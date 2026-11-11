import { venueApi } from "./flintplate";

export type StockUnit = "kg" | "l" | "piece";
export interface StockItem {
  id: string;
  sku: string;
  name: string;
  unit: StockUnit;
  requires_expiry: boolean;
  minimum_quantity: string;
}
export interface StockOwner { id: string; name: string; kind: "own" | "partner"; reference: string }
export interface StockLocation { id: string; name: string }
export interface StockLot {
  id: string;
  item_id: string;
  owner_id: string;
  code: string;
  expires_on: string | null;
  blocked: boolean;
  version: number;
}
export interface StockBalance {
  lot_id: string;
  item_id: string;
  owner_id: string;
  location_id: string;
  quantity: string;
  available_quantity: string;
  reserved_quantity: string;
  reservation_shortfall_quantity: string;
  expires_on: string | null;
  expired: boolean;
  blocked: boolean;
}
export interface StockOperation {
  id: string;
  sequence: number;
  request_key: string;
  kind: "receipt" | "transfer" | "waste" | "count" | "quarantine" | "production" | "consume" | "return";
  actor_id: string;
  reason: string;
  created_at: string;
  details: Record<string, unknown>;
  movements: { id: string; lot_id: string; location_id: string; quantity: string }[];
}
export interface InventorySnapshot {
  business_date: string;
  items: StockItem[];
  owners: StockOwner[];
  locations: StockLocation[];
  lots: StockLot[];
  balances: StockBalance[];
}

export function inventoryApi<T>(venueId: string, path: string, method = "GET", body?: unknown) {
  return venueApi<T>(venueId, `/inventory${path}`, method, body);
}

export const stockUnits: Record<StockUnit, string> = { kg: "kg", l: "l", piece: "Stück" };
export const stockOperationNames: Record<StockOperation["kind"], string> = {
  receipt: "Wareneingang", transfer: "Umlagerung", waste: "Schwund", count: "Inventur",
  quarantine: "Quarantäne", production: "Produktion", consume: "Verbrauch", return: "Eigentümerrückgabe",
};

/** Exact decimal arithmetic for display totals, including Decimal's exponent notation. */
export function stockMicros(value: string): bigint {
  const match = /^([+-]?)(\d+)(?:\.(\d+))?(?:[Ee]([+-]?\d+))?$/.exec(value);
  if (!match) return BigInt(0);
  const fraction = match[3] ?? "";
  const power = 6 + Number(match[4] ?? 0) - fraction.length;
  const digits = BigInt(match[2] + fraction) * (match[1] === "-" ? -BigInt(1) : BigInt(1));
  return power >= 0 ? digits * (BigInt(10) ** BigInt(power)) : digits / (BigInt(10) ** BigInt(-power));
}

export function formatStockMicros(value: bigint): string {
  const sign = value < BigInt(0) ? "−" : "";
  const absolute = value < BigInt(0) ? -value : value;
  const whole = new Intl.NumberFormat("de-DE").format(absolute / BigInt(1000000));
  const fraction = (absolute % BigInt(1000000)).toString().padStart(6, "0").replace(/0+$/, "");
  return `${sign}${whole}${fraction ? `,${fraction}` : ""}`;
}

export function stockQuantity(value: string): string {
  return formatStockMicros(stockMicros(value));
}
