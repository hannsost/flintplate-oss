import { newRequestId } from "./flintplate-uuid";
import type { Item } from "./flintplate";
import { matchesRoundRows, type RoundRowInput } from "./flintplate-rounds";

export const ORDER_DRAFT_PREFIX = "flintplate:order-draft:v1:";
export const AUTH_CHANGED_EVENT = "palmscout-auth-changed";
export const ORDER_DRAFT_CHANGED_EVENT = "flintplate-order-draft-changed";

export type Fulfillment = "dine_in" | "takeaway";
export interface OrderTarget { table: string; fulfillment: Fulfillment; visitId?: string }
export interface CartRow { item: Item; quantity: number; course?: number; rowId?: string; guestTabId?: string; note?: string }
export interface RoundRequest {
  request_key: string;
  accept_warnings?: boolean;
  visit_version: number;
  tab_versions: { guest_tab_id: string; version: number }[];
  fulfillment: Fulfillment;
  note: string;
  rows: RoundRowInput[];
}
export interface OrderRequest {
  request_key: string;
  version?: number;
  table_id: string | null;
  fulfillment: Fulfillment;
  guests: number;
  note: string;
  accept_warnings?: boolean;
  lines: { item_id: string; menu_version: number; quantity: number; note: string; course?: number }[];
}
export interface OrderDraft extends OrderTarget {
  requestKey: string;
  revision: string;
  cart: CartRow[];
  note: string;
  pending: OrderRequest | RoundRequest | null;
  uncertain: boolean;
  warning: string;
}

export function orderDraftScope(user: { sub: string; tenant_id: string | null } | null, endpoint: string) {
  if (!user?.sub) return null;
  // The endpoint includes the venue and separates guest/service authorizations.
  return ORDER_DRAFT_PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, endpoint]));
}

export function orderDraftKey(scope: string, target: OrderTarget) {
  if (target.visitId) return `${scope}:round:${encodeURIComponent(target.visitId)}`;
  return `${scope}:draft:${encodeURIComponent(JSON.stringify([target.fulfillment, target.fulfillment === "dine_in" ? target.table : ""]))}`;
}

export function emptyOrderDraft(target: OrderTarget): OrderDraft {
  return { ...target, requestKey: newRequestId(), revision: newRequestId(), cart: [], note: "", pending: null, uncertain: false, warning: "" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTarget(value: unknown): value is OrderTarget {
  return isRecord(value) && typeof value.table === "string" && (value.fulfillment === "dine_in" || value.fulfillment === "takeaway") && (value.visitId === undefined || (typeof value.visitId === "string" && !!value.visitId));
}

export function readOrderTarget(scope: string): OrderTarget | null {
  const raw = localStorage.getItem(`${scope}:active`);
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  if (!isTarget(value)) throw new Error("Der gespeicherte Tischkontext konnte nicht gelesen werden.");
  return value;
}

export function readOrderDraft(scope: string, target: OrderTarget): OrderDraft | null {
  const raw = localStorage.getItem(orderDraftKey(scope, target));
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  if (!isTarget(value) || !isRecord(value) || typeof value.requestKey !== "string" || typeof value.revision !== "string" || typeof value.note !== "string" || typeof value.uncertain !== "boolean" || typeof value.warning !== "string" || !Array.isArray(value.cart) || value.cart.some(row => !isRecord(row) || !Number.isInteger(row.quantity) || Number(row.quantity) < 1 || Number(row.quantity) > 99 || !isRecord(row.item) || typeof row.item.id !== "string" || typeof row.item.name !== "string" || !Number.isInteger(row.item.price_cents) || !Number.isInteger(row.item.version) || (value.visitId && (typeof row.rowId !== "string" || !row.rowId || typeof row.guestTabId !== "string" || !row.guestTabId || (row.note !== undefined && typeof row.note !== "string")))) || (value.pending !== null && (!isRecord(value.pending) || value.pending.request_key !== value.requestKey || !(value.visitId ? Array.isArray(value.pending.rows) : Array.isArray(value.pending.lines))))) {
    throw new Error("Der gespeicherte Entwurf konnte nicht sicher gelesen werden. Bitte den Service kontaktieren; es wurde nichts gesendet.");
  }
  if (value.visitId !== target.visitId || (!value.visitId && (value.table !== target.table || value.fulfillment !== target.fulfillment))) throw new Error("Der Entwurf gehört zu einem anderen Besuch oder Tisch.");
  if (isRecord(value.pending)) {
    const pending = value.pending;
    const rows = value.cart as CartRow[];
    if (value.visitId) {
      const guests = new Set(rows.map(row => row.guestTabId));
      const versions = pending.tab_versions;
      const validVersions = Array.isArray(versions) && versions.length === guests.size && versions.every((entry: unknown) => isRecord(entry) && typeof entry.guest_tab_id === "string" && guests.has(entry.guest_tab_id) && Number.isInteger(entry.version) && Number(entry.version) > 0) && new Set(versions.map(entry => entry.guest_tab_id)).size === guests.size;
      if (!matchesRoundRows(rows, pending.rows) || !Number.isInteger(pending.visit_version) || Number(pending.visit_version) < 1 || !validVersions || pending.fulfillment !== value.fulfillment || pending.note !== value.note) throw new Error("Der gespeicherte Sendevorgang passt nicht zur Runde. Es wurde nichts gesendet.");
    } else {
    const validLines = Array.isArray(pending.lines) && pending.lines.length === rows.length && pending.lines.every((line: unknown, index: number) => {
      const row = rows[index];
      return isRecord(line) && line.item_id === row.item.id && line.quantity === row.quantity && line.menu_version === row.item.version && (line.course ?? 1) === (row.course ?? 1) && typeof line.note === "string";
    });
    if (!validLines || pending.fulfillment !== value.fulfillment || pending.table_id !== (value.fulfillment === "dine_in" ? value.table || null : null) || pending.note !== value.note) {
      throw new Error("Der gespeicherte Sendevorgang passt nicht zum Entwurf. Bitte den Service kontaktieren; es wurde nichts gesendet.");
    }
    }
  }
  if (value.uncertain && value.pending === null) throw new Error("Die Vorgangs-ID der ausstehenden Bestellung fehlt. Bitte den Service kontaktieren.");
  return value as unknown as OrderDraft;
}

export function writeOrderDraft(scope: string, draft: OrderDraft, rememberTarget = true) {
  localStorage.setItem(orderDraftKey(scope, draft), JSON.stringify(draft));
  if (rememberTarget) localStorage.setItem(`${scope}:active`, JSON.stringify({ table: draft.table, fulfillment: draft.fulfillment, ...(draft.visitId ? { visitId: draft.visitId } : {}) }));
}

/** Logout and changing accounts remove private drafts from this shared browser. */
export function clearOrderDrafts() {
  for (let index = localStorage.length - 1; index >= 0; index--) {
    const key = localStorage.key(index);
    if (key && [ORDER_DRAFT_PREFIX, "flintplate:service-context:v1:", "flintplate:split-context:v1:", "flintplate:visit-pending:v1:", "flintplate:payment-group-pending:v1:", "flintplate:payment-context:v1:", "flintplate:task-pending:v1:", "flintplate:cancellation-pending:v1:", "flintplate:layout-pending:v1:", "flintplate:purchase-editor:v1:", "flintplate:delivery-pending:v1:", "flintplate:labour-pending:v1:", "flintplate:bonus-pending:v1:", "flintplate:station-pending:v1:", "flintplate:station-filter:v1:", "flintplate:cash-pending:v1:", "flintplate:recall-pending:v1:", "flintplate:inventory-pending:v1:", "flintplate:purchasing-pending:v1:", "flintplate:production-pending:v1:", "flintplate:reservation-pending:v1:", "flintplate:inventory-reservation-pending:v1:", "flintplate:partner-pending:v1:", "flintplate:hygiene-pending:v1:"].some(prefix => key.startsWith(prefix))) localStorage.removeItem(key);
  }
}
