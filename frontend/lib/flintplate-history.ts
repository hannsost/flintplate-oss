import { venueApi, type Order } from "./flintplate";

export interface OrderHistoryPage { items: Order[]; next_before: string | null; has_more: boolean }
export interface AuditEvent {
  venue_id: string; actor_id: string | null; device_id: string | null;
  sequence: number; audit_sequence: number | null; kind: string; aggregate_id: string;
  payload: Record<string, unknown>; created_at: string;
  previous_hash: string | null; event_hash: string | null; canonical_payload: string | null;
}
export interface AuditPage { items: AuditEvent[]; through_sequence: number; next_after: number; has_more: boolean }

export async function auditPage(venueId: string, after = 0, through?: number): Promise<AuditPage> {
  const page = await venueApi<AuditPage>(venueId, `/audit-events?after=${after}&limit=500${through === undefined ? "" : `&through=${through}`}`);
  if (through !== undefined && page.through_sequence !== through) throw new Error("Der Journal-Endstand hat sich verändert. Bitte neu laden.");
  let previous = after;
  for (const row of page.items) {
    if (row.venue_id !== venueId || row.sequence <= previous || row.sequence > page.through_sequence) throw new Error("Die Journalfolge ist nicht vollständig prüfbar. Der Export wurde angehalten.");
    previous = row.sequence;
  }
  if (page.has_more && (!page.items.length || page.next_after !== previous || page.next_after <= after)) throw new Error("Die nächste Journalseite konnte nicht sicher bestimmt werden.");
  return page;
}
