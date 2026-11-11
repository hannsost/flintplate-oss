import { request, apiErrorMessage } from "./api";

export const permissionNames = { read: "Lesen", prepare: "Vorbereiten", approve: "Prüfen", issue: "Finalisieren", export: "Exportieren", manage: "Finanzrechte verwalten" };
export type Permission = keyof typeof permissionNames;
export interface Party { name: string; street: string; postal_code: string; city: string; country: "DE"; email: string }
export interface EntityInput extends Party { vat_id: string; contact_name: string; phone: string; iban: string; invoice_prefix: string; four_eyes: boolean }
export interface Entity extends EntityInput { id: string; version: number; permissions: Permission[] }
export interface Grant { user_id: string; name: string; permissions: Permission[]; version: number }
export interface InvoiceLine { description: string; quantity: string; unit: "HUR" | "C62"; unit_price: string; vat_rate: 19 }
export interface InvoiceInput { buyer: Party; buyer_reference: string; service_reference: string; issue_date: string; due_date: string; service_start: string; service_end: string; currency: "EUR"; lines: InvoiceLine[] }
export interface Invoice { id: string; entity_id: string; kind: string; original_id: string | null; status: string; version: number; number: string | null; buyer_name: string; issue_date: string; service_reference: string; total: string; payload: { seller: EntityInput; invoice: InvoiceInput; totals: { net: string; tax: string; gross: string }; original_number?: string }; payload_hash: string; prepared_by: string | null; approved_by: string | null; artifact_hash: string | null; validation: { status: string; validator: string; rules: string; errors: string[] } | null }
export interface FinanceEvent { action: string; note: string; actor_id: string | null; created_at: string }
export const invoiceStates: Record<string, string> = { draft: "Entwurf", in_review: "In Prüfung", approved: "Freigegeben", finalized: "Finalisiert", cancelled: "Storniert" };
export const financeApi = {
  entities: (t: string) => request<Entity[]>("/finance/entities", {}, t),
  entity: (t: string, data: EntityInput, old?: Entity) => request<Entity>(`/finance/entities${old ? `/${old.id}` : ""}`, { method: old ? "PUT" : "POST", body: JSON.stringify({ ...data, ...(old ? { version: old.version } : {}) }) }, t),
  grants: (t: string, id: string) => request<Grant[]>(`/finance/entities/${id}/grants`, {}, t),
  grant: (t: string, id: string, g: Grant) => request<Grant>(`/finance/entities/${id}/grants`, { method: "PUT", body: JSON.stringify({ user_id: g.user_id, permissions: g.permissions, version: g.version }) }, t),
  invoices: (t: string, id: string, offset = 0) => request<Invoice[]>(`/finance/invoices?entity_id=${id}&offset=${offset}`, {}, t),
  invoice: (t: string, id: string) => request<Invoice>(`/finance/invoices/${id}`, {}, t),
  save: (t: string, entity: string, data: InvoiceInput, key: string, old?: Invoice) => request<Invoice>(old ? `/finance/invoices/${old.id}` : `/finance/entities/${entity}/invoices`, { method: old ? "PUT" : "POST", body: JSON.stringify({ ...data, ...(old ? { version: old.version } : { request_key: key }) }) }, t),
  decision: (t: string, i: Invoice, action: string, note: string) => request<Invoice>(`/finance/invoices/${i.id}/${action}`, { method: "POST", body: JSON.stringify({ version: i.version, note }) }, t),
  credit: (t: string, i: Invoice, note: string, issue_date: string, request_key: string) => request<Invoice>(`/finance/invoices/${i.id}/credit`, { method: "POST", body: JSON.stringify({ version: i.version, note, issue_date, request_key }) }, t),
  events: (t: string, id: string) => request<FinanceEvent[]>(`/finance/invoices/${id}/events`, {}, t),
  download: async (t: string, i: Invoice, report = false) => {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001"}/finance/invoices/${i.id}/download?report=${report}`, { headers: { Authorization: `Bearer ${t}` }, cache: "no-store" });
    if (!response.ok) { const error = await response.json().catch(() => null); throw new Error(apiErrorMessage(error?.detail, "Download fehlgeschlagen.")); }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${i.number ?? i.id}${report ? "-pruefbericht" : ""}.xml`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
export const euro = (value: string) => new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(Number(value));
export const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
