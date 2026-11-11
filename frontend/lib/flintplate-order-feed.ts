import { venueApi, type Order } from "./flintplate";

/** Closed history must never push an older active table out of the work queue. */
export async function loadOrderFeed(venueId: string, includeRecentClosed = true): Promise<Order[]> {
  const active = new Map<string, Order>();
  const cursors = new Set<string>();
  let before = "";
  for (;;) {
    const page = await venueApi<Order[]>(venueId, `/orders?limit=500${before ? `&before=${encodeURIComponent(before)}` : ""}`);
    for (const order of page) active.set(order.id, order);
    if (active.size > 10000 || cursors.size > 20) {
      throw new Error("Mehr als 10.000 aktive Bons: Die vollständige Arbeitsliste kann nicht geladen werden. Bitte die Betriebsleitung informieren und alte offene Vorgänge prüfen.");
    }
    if (page.length < 500) break;
    const cursor = page.at(-1)?.id;
    if (!cursor || cursors.has(cursor)) throw new Error("Die vollständige Bonliste konnte nicht geladen werden. Bitte erneut aktualisieren.");
    cursors.add(cursor);
    before = cursor;
  }
  if (includeRecentClosed) {
    const recent = await venueApi<Order[]>(venueId, "/orders?include_closed=true&limit=100");
    for (const order of recent) {
      const previous = active.get(order.id);
      if (!previous || order.version >= previous.version) active.set(order.id, order);
    }
  }
  return [...active.values()].sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id.localeCompare(left.id));
}
