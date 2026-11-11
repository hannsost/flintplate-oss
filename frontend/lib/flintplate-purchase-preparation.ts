export interface SupplierSourceOption {
  supplier_id: string; supplier_name: string; product_id: string;
  price_id: string; price_version: number; price_effective_on: string;
  supplier_terms_id: string | null; supplier_terms_version: number | null;
  supplier_sku: string; pack_name: string; pack_quantity: string; unit: string; currency: string;
  need_quantity: string; packs: number | null; bonus_packs: number | null;
  paid_quantity: string | null; ordered_bonus_quantity: string | null;
  ordered_quantity: string | null; overage_quantity: string | null;
  pack_price_cents: number | null; net_cents: number | null; tax_rate_bps: number;
  earliest_delivery_on: string | null; minimum_order_net_cents: number | null;
  shortfall_to_minimum_net_cents: number | null; blocking_reasons: string[];
}

export interface PurchasePreparationIntent { item_name: string; source: SupplierSourceOption }
export interface PurchaseEditorDraft {
  key: string; supplier_id: string; owner_id: string; location_id: string;
  expected_on: string; reason: string; packs: Record<string, string>;
  price_ids: Record<string, string>; supplier_terms_id: string | null;
}
export const PURCHASE_EDITOR_PREFIX = "flintplate:purchase-editor:v1:";

/** Stored edits are never a write command: confirmation creates the pending payload. */
export function readPurchaseEditor(raw: string | null): PurchaseEditorDraft | null {
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") throw new Error("Ungültiger Einkaufsentwurf.");
  const row = value as Record<string, unknown>;
  if (!["key", "supplier_id", "owner_id", "location_id", "expected_on", "reason"].every(key => typeof row[key] === "string") || !row.key || !row.supplier_id || !(row.supplier_terms_id === null || typeof row.supplier_terms_id === "string")) throw new Error("Ungültiger Einkaufsentwurf.");
  for (const key of ["packs", "price_ids"]) {
    const fields = row[key];
    if (!fields || typeof fields !== "object" || Array.isArray(fields) || !Object.values(fields).every(field => typeof field === "string")) throw new Error("Ungültige Positionen im Einkaufsentwurf.");
  }
  return value as PurchaseEditorDraft;
}

export function preparePurchaseEditor(intent: PurchasePreparationIntent, key: string): PurchaseEditorDraft {
  const source = intent.source;
  if (source.packs === null || !Number.isInteger(source.packs) || source.packs <= 0) throw new Error("Für diesen Vorschlag ist keine bestellbare Gebindemenge berechnet.");
  return { key, supplier_id: source.supplier_id, owner_id: "", location_id: "", expected_on: "", reason: `Mindestbestand ${intent.item_name}`.slice(0, 300), packs: { [source.product_id]: String(source.packs) }, price_ids: { [source.product_id]: source.price_id }, supplier_terms_id: source.supplier_terms_id };
}
