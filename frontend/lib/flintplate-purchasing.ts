import { venueApi } from "./flintplate";
import type { StockUnit } from "./flintplate-inventory";

export interface Supplier { id: string; name: string; reference: string; contact: string }
export interface ProductConditions { schema_version: 1; minimum_paid_packs: number; order_multiple: number; tier_mode: "all_units"; tiers: { minimum_paid_packs: number; pack_price_cents: number }[]; natural_rebate: { buy_packs: number; free_packs: number } | null }
export interface SupplierRules { minimum_order_net_cents: number; lead_time_calendar_days: number; delivery_weekdays: number[]; excluded_delivery_dates: string[]; order_cutoff_local: string | null }
export interface SupplierTerms { id: string; supplier_id: string; version: number; effective_on: string; rules: SupplierRules }
export interface SupplierPrice { conditions: ProductConditions; id: string; product_id: string; version: number; effective_on: string; pack_price_cents: number; tax_rate_bps: number }
export interface SupplierProduct {
  id: string; supplier_id: string; item_id: string; supplier_sku: string; pack_name: string;
  pack_quantity: string; version: number; current_price: SupplierPrice | null; prices: SupplierPrice[];
}
export interface PurchaseLine {
  id: string; product_id: string; item_id: string; price_id: string; item_name: string; unit: StockUnit;
  supplier_sku: string; pack_name: string; pack_quantity: string; packs: number;
  ordered_bonus_quantity: string; received_bonus_quantity: string; remaining_bonus_quantity: string; billable_received_quantity: string; conditions_snapshot: ProductConditions;
  ordered_quantity: string; received_quantity: string; rejected_quantity: string; remaining_quantity: string;
  pack_price_cents: number; tax_rate_bps: number; net_cents: number;
}
export interface PurchaseReceipt { confirmation_id: string | null;
  id: string; line_id: string; stock_operation_id: string | null; accepted_quantity: string;
  accepted_bonus_quantity: string; rejected_bonus_quantity: string;
  rejected_quantity: string; reference: string; rejection_reason: string; details: Record<string, unknown>;
}
export interface PurchaseOrder {
  supplier_terms_id: string | null; supplier_terms_snapshot: Partial<SupplierRules>; earliest_delivery_on: string | null; shortfall_to_minimum_net_cents: number;
  id: string; supplier_id: string; owner_id: string; location_id: string; number: string;
  status: "draft" | "ordered" | "partial" | "received" | "closed" | "cancelled";
  version: number; expected_on: string | null; currency: string; note: string;
  lines: PurchaseLine[]; receipts: PurchaseReceipt[]; net_cents: number; tax_cents: number; total_cents: number;
}
export interface InvoiceCheckLine {
  received_bonus_quantity: string;
  purchase_line_id: string; quantity: string; net_cents: number; tax_rate_bps: number;
  item_name: string; unit: StockUnit; expected_net_cents: number; received_quantity: string;
  already_invoiced_quantity: string; differences: string[];
}
export interface PurchaseInvoice {
  id: string; supplier_id: string; number: string; issued_on: string; currency: string;
  status: "draft" | "approved" | "rejected"; version: number; decision_reason: string;
  check: { matched: boolean; lines: InvoiceCheckLine[]; net_cents: number; tax_cents: number; total_cents: number };
}
export interface PurchasingSnapshot {
  supplier_terms: SupplierTerms[];
  business_date: string; suppliers: Supplier[]; catalog: SupplierProduct[];
  orders: PurchaseOrder[]; invoices: PurchaseInvoice[];
}
export function purchasingApi<T>(venueId: string, path: string, method = "GET", body?: unknown) {
  return venueApi<T>(venueId, `/purchasing${path}`, method, body);
}
export const purchaseStates: Record<PurchaseOrder["status"], string> = {
  draft: "Entwurf", ordered: "Freigegeben", partial: "Teillieferung", received: "Vollständig erhalten",
  closed: "Restlieferung geschlossen", cancelled: "Storniert",
};
/** Form amounts have at most two decimal places; avoid floating-point multiplication. */
export function inputCents(value: string): number {
  const [whole, fraction = ""] = value.replace(",", ".").split(".");
  return Number(whole || "0") * 100 + Number(fraction.padEnd(2, "0").slice(0, 2));
}
