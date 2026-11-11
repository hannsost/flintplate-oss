import { venueApi } from "./flintplate";

export interface PartnerRules {
  revenue_basis: "net" | "gross"; share_bps: number; revenue_threshold_cents: number;
  per_sale_cents: number; fixed_monthly_cents: number; minimum_monthly_cents: number | null;
  loss_responsibility: "venue" | "partner"; loss_per_stock_unit_cents: number;
}
export interface PartnerTerms { id: string; version: number; effective_on: string; active: boolean; stock_per_sale: string; rules: PartnerRules }
export interface PartnerContract { id: string; name: string; owner_id: string; item_id: string; menu_item_id: string; currency: string; terms: PartnerTerms[] }
export interface PartnerEvent { id: string; created_at: string; contract_id: string; kind: string; source_month: string; posting_month: string; physical_quantity: string; gross_cents: number; net_cents: number; unit_fee_cents: number; loss_cents: number; stock_operation_id: string | null; original_id: string | null; line_id: string | null; unit: number | null; evidence: Record<string, unknown>[] }
export interface SettlementComponent { source_month: string; revenue_cents: number; share_cents: number; unit_fees_cents: number; fixed_cents: number; guarantee_topup_cents: number; loss_cents: number; calculated_payable_cents: number; previously_settled_cents: number; delta_cents: number }
export interface SettlementPreview { contract_id: string; month: string; payable_to_partner_cents: number; currency: string; components: SettlementComponent[]; fingerprint: string }
export interface PartnerSettlement { id: string; contract_id: string; month: string; payable_to_partner_cents: number; snapshot: SettlementPreview; reason: string }
export interface LoanEntry { id: string; created_at: string; kind: string; quantity: number; amount_cents: number; cash_entry_id: string | null; external_reference: string; reason: string }
export interface LoanAccount { id: string; owner_id: string; name: string; reference: string; serialized: boolean; deposit_per_unit_cents: number; currency: string; physical_quantity: number; received_quantity: number; returned_quantity: number; broken_quantity: number; deposit_claim_cents: number; unpaid_deposit_cents: number; refundable_deposit_cents: number; entries: LoanEntry[] }
export interface PartnerSnapshot { business_date: string; contracts: PartnerContract[]; events: PartnerEvent[]; settlements: PartnerSettlement[]; loans: LoanAccount[]; unassigned_losses: { stock_operation_id: string; owner_id: string; item_id: string; quantity: string; occurred_on: string; reason: string }[] }
export interface PartnerCandidates { order_id: string; sales: { contract_id: string; line_id: string; name: string; units: number[]; gross_cents: number; stock_quantity: string }[]; refunds: { contract_id: string; cash_entry_id: string; gross_cents: number }[]; notes: string[] }
export const partnerKinds: Record<string, string> = { sale: "Verkauf", refund: "Geldrückzahlung", return: "Eigentümerrückgabe", waste: "Bruch / Verlust", received: "Leihgut erhalten", returned: "Leihgut zurückgegeben", broken: "Leihgut verloren", deposit_paid: "Pfand bezahlt", deposit_refunded: "Pfand zurückerhalten", deposit_forfeited: "Pfand verfallen" };
export function partnerApi<T>(venueId: string, path: string, method = "GET", body?: unknown) { return venueApi<T>(venueId, `/partners${path}`, method, body); }
export function followingMonth(month: string): string { const [year, value] = month.split("-").map(Number); return `${year + (value === 12 ? 1 : 0)}-${String(value % 12 + 1).padStart(2, "0")}-01`; }
