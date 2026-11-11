export interface PaymentScope { visit_id?: string; guest_tab_ids?: string[]; order_ids?: string[] }
export interface UnitAmount { order_id: string; line_id: string; unit: number; amount_cents?: number }
export interface PaymentSelection { scope: PaymentScope; mode: "all" | "amount" | "units" | "parts" | "tip_only"; units: UnitAmount[]; part_ids: string[]; amount_cents: number | null; new_tip_cents: number; recipient_id: string | null; payer_tab_id: string | null; payer_label: string }
export interface PaymentBlocker { code: string; message: string; order_id: string | null }
export interface PaymentUnit { order_id: string; order_number: string; line_id: string; unit: number; name: string; kind: string; gross_cents: number; tax_cents: number; paid_cents: number; remaining_cents: number; cancelled: boolean; guest_tab_id: string | null; guest_label: string; assignment_id: string | null; assignment_version: number | null }
export interface PaymentOrder { order_id: string; number: string; version: number; cancellation_version: number | null; payment_status: string; fulfillment_status: string; remaining_cents: number; refund_due_cents: number; checkout_blocked: boolean }
export interface PaymentBalance { has_more: boolean; next_before_order_id: string | null; page_totals: true; currency: string; source_hash: string; orders: PaymentOrder[]; units: PaymentUnit[]; remaining_cents: number; refund_due_cents: number; blockers: PaymentBlocker[] }
export interface PaymentAllocation { order_id: string; line_id: string; unit: number; name: string; kind: string; amount_cents: number; tax_cents: number }
export interface PaymentQuote { quote_hash: string; source_hash: string; currency: string; orders: PaymentOrder[]; allocations: PaymentAllocation[]; receipt_amount_cents: number; new_tip_cents: number; amount_cents: number; selected_remaining_cents: number; payer_tab_id: string | null; payer_label: string; recipient_id: string | null; blockers: PaymentBlocker[] }
export interface PaymentGroup { id: string; created_at: string; session_id: string; currency: string; payer_tab_id: string | null; payer_label: string; receipt_amount_cents: number; new_tip_cents: number; amount_cents: number; received_cents: number; change_cents: number; quote_hash: string; allocations: PaymentAllocation[]; entries: { id: string; order_id: string | null; amount_cents: number }[]; tip_entry_id: string | null; part_payments: Record<string, unknown>[] }
export interface EqualPart { id: string; ordinal: number; payer_tab_id: string | null; label: string; target_cents: number; paid_cents: number; remaining_cents: number; unit_budgets: UnitAmount[] }
export interface EqualPlan { id: string; root_plan_id: string; revision: number; created_at: string; currency: string; source_hash: string; source_scope: PaymentScope; source_order_ids: string[]; total_cents: number; paid_cents: number; remaining_cents: number; status: "open" | "paid" | "stale" | "abandoned" | "superseded"; next_plan_id: string | null; parts: EqualPart[]; blockers: PaymentBlocker[] }

/** A navigation preference is never authority for a pending payer selection. */
export function planMatchesPayment(input: PaymentSelection, plan: EqualPlan): boolean {
  return input.mode === "parts" && input.part_ids.length > 0 && new Set(input.part_ids).size === input.part_ids.length && input.part_ids.every(id => plan.parts.some(part => part.id === id));
}
export interface PayerTip { id: string; payment_group_id: string; original_id: string | null; kind: string; amount_cents: number; session_id: string; currency: string; payer_tab_id: string | null; payer_label: string; recipient_id: string | null; reason: string; created_at: string; refunded_cents: number; refundable_cents: number; tip_run_id: string | null }

export const paymentUnitKey = (unit: Pick<PaymentUnit, "order_id" | "line_id" | "unit">) => `${unit.order_id}:${unit.line_id}:${unit.unit}`;
/** User-entered decimal money, never floating-point multiplication for posted cents. */
export function euroCents(value: string, maximum = 100000000): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d+(?:\.\d{0,2})?$/.test(normalized)) return null;
  const [whole, decimal = ""] = normalized.split(".");
  const result = Number(whole) * 100 + Number(decimal.padEnd(2, "0"));
  return Number.isSafeInteger(result) && result <= maximum ? result : null;
}
export const euroInput = (value: number) => `${Math.floor(value / 100)}.${String(value % 100).padStart(2, "0")}`;

/** A financial fraction keeps the original physical unit and all source IDs. */
export function selectedUnitAmounts(units: PaymentUnit[], chosen: Record<string, string>): UnitAmount[] {
  return units.filter(unit => Object.hasOwn(chosen, paymentUnitKey(unit))).map(unit => {
    const raw = chosen[paymentUnitKey(unit)], amount = raw === "" ? unit.remaining_cents : euroCents(raw);
    if (unit.cancelled || amount === null || amount <= 0 || amount > unit.remaining_cents) throw new Error(`Bitte einen Betrag innerhalb des offenen Rests für ${unit.name} wählen.`);
    return { order_id: unit.order_id, line_id: unit.line_id, unit: unit.unit, ...(raw ? { amount_cents: amount } : {}) };
  });
}

export function groupPaymentUnits(units: PaymentUnit[]): PaymentUnit[][] {
  const groups = new Map<string, PaymentUnit[]>();
  for (const unit of units) { const key = `${unit.order_id}:${unit.line_id}:${unit.guest_tab_id ?? ""}`; groups.set(key, [...(groups.get(key) ?? []), unit]); }
  return [...groups.values()];
}
