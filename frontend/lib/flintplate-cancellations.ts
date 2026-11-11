import { venueApi, type Order } from "./flintplate";

export const CANCELLATION_PENDING = "flintplate:cancellation-pending:v1:";
export const CANCELLATION_PATH = /^\/(?:orders\/[0-9a-f-]+\/cancellations(?:\/[0-9a-f-]+\/decision)?|cancellations\/[0-9a-f-]+\/ack)$/i;
export const cancellationReasons = { entry_error: "Falsch erfasst / doppelt bestellt", guest_request: "Auf Wunsch des Gastes", quality: "Qualitätsmangel / Reklamation", unavailable: "Nicht verfügbar", other: "Anderer Grund" };
export type CancellationReason = keyof typeof cancellationReasons;
export interface CancellationSelection { version: number; whole_order: boolean; include_tip: boolean; lines: { line_id: string; quantity: number }[]; reason_code: CancellationReason; note: string }
export interface CancellationLine { line_id: string; name: string; quantity: number; units: number[]; preparation_status: string; station: string; kind: string; gross_cents: number; tax_cents: number; stock_effect: "not_consumed" | "consumption_retained" }
export interface CancellationPreview { order_id: string; order_number: string; order_version: number; preview_hash: string; lines: CancellationLine[]; gross_cents: number; tax_cents: number; money: Record<string, unknown>; warnings: string[] }
export interface CancellationAcknowledgement { id: string; execution_id: string; actor_id: string; created_at: string }
export interface CancellationExecution { id: string; order_id: string; order_number: string; actor_id: string; reason_code: string; note: string; order_version: number; result_version: number; lines: CancellationLine[]; money: Record<string, unknown>; checkout_reconciliation_required: boolean; kitchen_required: boolean; created_at: string; acknowledgement: CancellationAcknowledgement | null }
export interface CancellationRequest { id: string; order_id: string; order_number: string; requester_id: string; original_actor_id: string | null; order_version: number; reason_code: string; note: string; source: string; created_at: string; preview: CancellationPreview; decision: { id: string; actor_id: string; decision: "approve" | "reject"; note: string; self_approved: boolean; created_at: string } | null; execution: CancellationExecution | null }
export function cancelledQuantity(order: Order, lineId: string) { return (order.cancelled_units ?? []).filter(unit => unit.line_id === lineId).length; }
export function remainingOrderQuantity(order: Order, lineId: string) { return Math.max(0, (order.lines.find(line => line.line_id === lineId)?.quantity ?? 0) - cancelledQuantity(order, lineId)); }
export function cancelledOrderCents(order: Order) { return (order.cancelled_units ?? []).reduce((total, unit) => total + unit.gross_cents, 0); }
export function correctedOrderCents(order: Order) { return order.total_cents + order.tip_cents - cancelledOrderCents(order); }
/** The guest receipt is not a cash balance. After cancellation the immutable
 * original tip must be replayed, even when a cancellation has credited it. */
export function guestPaymentProposal(order: Order, selectedTip: number) {
  const tipLocked = (order.cancelled_units?.length ?? 0) > 0;
  const requestTip = tipLocked ? order.tip_cents : selectedTip;
  return { tipLocked, requestTip, receiptCents: correctedOrderCents(order) + (tipLocked ? 0 : requestTip - order.tip_cents) };
}
export function cancellationBlockers(value: { money: Record<string, unknown> }) { return Array.isArray(value.money.blockers) ? value.money.blockers.filter((item): item is string => typeof item === "string") : []; }

/** Retrieve all pages for a single receipt or the outstanding kitchen queue. */
export async function cancellationPages<T extends { id: string }>(venueId: string, path: string): Promise<T[]> {
  const values = new Map<string, T>(), cursors = new Set<string>();
  let before = "";
  for (;;) {
    const page = await venueApi<T[]>(venueId, `${path}${path.includes("?") ? "&" : "?"}limit=50${before ? `&before=${before}` : ""}`);
    for (const row of page) values.set(row.id, row);
    if (page.length < 50) return [...values.values()];
    const next = page.at(-1)?.id;
    if (!next || cursors.has(next)) throw new Error("Die vollständige Stornohistorie konnte nicht geladen werden. Bitte erneut versuchen.");
    cursors.add(next); before = next;
  }
}
