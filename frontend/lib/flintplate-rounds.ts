import type { CartRow } from "./flintplate-drafts";

export interface RoundRowInput {
  cart_row_id: string;
  item_id: string;
  menu_version: number;
  quantity: number;
  course: number;
  note: string;
  assignments: { guest_tab_id: string; units: number[] }[];
}

/** Rows for two guests must never collapse merely because their menu item is equal. */
export function cartRowKey(row: CartRow): string {
  return row.rowId ?? row.item.id;
}

export function changeRoundQuantity(cart: CartRow[], item: CartRow["item"], guestTabId: string, delta: number, rowId: string): CartRow[] {
  const previous = cart.find(row => row.guestTabId === guestTabId && row.item.id === item.id);
  if (!previous) return delta > 0 ? [...cart, { item, quantity: 1, guestTabId, rowId }] : cart;
  return cart.map(row => row === previous ? { ...row, quantity: Math.min(99, row.quantity + delta) } : row).filter(row => row.quantity > 0);
}

export function roundRows(cart: CartRow[]): RoundRowInput[] {
  const seen = new Set<string>();
  return cart.map(row => {
    if (!row.rowId || !row.guestTabId || seen.has(row.rowId) || !Number.isInteger(row.quantity) || row.quantity < 1 || row.quantity > 99) throw new Error("Die Gästezuordnung dieser Runde ist unvollständig. Bitte die Auswahl prüfen.");
    seen.add(row.rowId);
    return { cart_row_id: row.rowId, item_id: row.item.id, menu_version: row.item.version, quantity: row.quantity, course: row.course ?? 1, note: row.note ?? "", assignments: [{ guest_tab_id: row.guestTabId, units: Array.from({ length: row.quantity }, (_, index) => index) }] };
  });
}

/** Defensive persisted-payload validation, including quantities and guest identity. */
export function matchesRoundRows(cart: CartRow[], rows: unknown): boolean {
  try { return JSON.stringify(rows) === JSON.stringify(roundRows(cart)); }
  catch { return false; }
}
