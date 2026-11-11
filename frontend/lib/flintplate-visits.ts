import type { Order } from "./flintplate";

export interface ServiceSettings { workflow: "table" | "guest" | "counter" | "mixed"; guest_label_mode: "number" | "name_or_number" | "seat_or_number"; version: number }
export interface GuestTab { id: string; venue_id: string; visit_id: string; kind: "guest" | "shared"; number: number; label: string; current_table_id: string | null; seat_label: string; present: boolean; version: number; created_at: string }
export interface ServiceVisit { id: string; venue_id: string; number: string; label: string; version: number; reservation_id: string | null; ended_at: string | null; created_at: string; tabs: GuestTab[] }
export interface ServicePage<T> { items: T[]; next_before: string | null; has_more: boolean }
export interface ServiceRound { id: string; visit_id: string; number: number; created_at: string; children: { guest_tab_id: string; order_id: string; number: string; label_snapshot: string; order: Order }[] }
export interface ServiceCommand { id: string; kind: string; actor_id: string; reason: string; target_id: string; snapshots: Record<string, unknown>[]; result: Record<string, unknown>; created_at: string }
export interface UnitKey { order_id: string; line_id: string; unit: number }
export interface AssignedUnit extends UnitKey { id: string; guest_tab_id: string; before_tab_id: string | null; version: number; cart_row_id: string | null; cart_unit: number | null }
export interface OrderServiceContext { order_id: string; round_id: string | null; round_number: number | null; visit_id: string; visit_number: string; tabs: GuestTab[]; assignments: AssignedUnit[] }
export interface TablePresence { table_id: string; visit_ids: string[]; guest_tab_ids: string[]; guest_count: number }

export function guestTabLabel(tab: Pick<GuestTab, "kind" | "label" | "number" | "seat_label">, mode: ServiceSettings["guest_label_mode"] = "name_or_number"): string {
  if (tab.kind === "shared") return "Gemeinsam";
  if (mode === "seat_or_number" && tab.seat_label) return `Platz ${tab.seat_label}${tab.label ? ` · ${tab.label}` : ""}`;
  return mode !== "number" && tab.label ? `${tab.label} · Gast ${tab.number}` : `Gast ${tab.number}`;
}
export const visitLabel = (visit: Pick<ServiceVisit, "number" | "label">) => visit.label ? `${visit.label} · ${visit.number}` : visit.number;
export const serviceWorkflows = { table: "Tisch / Sitzplatz", guest: "Gastname / Gastnummer", counter: "Theke / Takeaway / Bon", mixed: "Gemischt" };

/** Context-bound guests determine presence; a partial legacy assignment must
 * still retain the original table's unassigned, non-cancelled product units. */
export function usesOriginalTable(order: Order, context?: OrderServiceContext): boolean {
  if (!context) return true;
  if (context.round_id) return false;
  const assigned = new Set(context.assignments.map(value => `${value.line_id}:${value.unit}`));
  const cancelled = new Set(order.cancelled_units?.map(value => `${value.line_id}:${value.unit}`) ?? []);
  return order.lines.some(line => line.kind === "product" && Array.from({ length: line.quantity }, (_, unit) => `${line.line_id}:${unit}`).some(key => !cancelled.has(key) && !assigned.has(key)));
}
