"use client";

import { useRef, useState, type FormEvent } from "react";
import { type Entity, type EntityInput, type Invoice, type InvoiceInput, type InvoiceLine, type Party, today } from "@/lib/finance";

export const field = "mt-1 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-50";
export const button = "min-h-11 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";
export const primary = "min-h-11 rounded-xl bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50";
export const box = "rounded-2xl border border-slate-200 bg-white p-5 sm:p-6";

function PartyFields({ data, prefix }: { data?: Party; prefix: string }) {
  return <div className="grid gap-4 sm:grid-cols-2">
    {([['name', 'Name / Firma', 200], ['street', 'Straße und Hausnummer', 200], ['postal_code', 'Postleitzahl', 5], ['city', 'Ort', 100], ['email', 'E-Mail', 254]] as const).map(([key, label, max]) => <label className="text-sm" key={key}>{label}<input name={`${prefix}_${key}`} aria-label={`${prefix === "seller" ? "Aussteller" : "Empfänger"} ${label}`} className={field} type={key === "email" ? "email" : "text"} maxLength={max} pattern={key === "postal_code" ? "[0-9]{5}" : undefined} defaultValue={data?.[key]} required /></label>)}
    <p className="self-end pb-3 text-sm text-slate-600">Land: Deutschland</p>
  </div>;
}
function readParty(data: FormData, prefix: string): Party {
  return { name: String(data.get(`${prefix}_name`)), street: String(data.get(`${prefix}_street`)), postal_code: String(data.get(`${prefix}_postal_code`)), city: String(data.get(`${prefix}_city`)), email: String(data.get(`${prefix}_email`)), country: "DE" };
}

export function EntityForm({ value, busy, save }: { value?: Entity; busy: boolean; save: (data: EntityInput) => Promise<void> }) {
  return <form onSubmit={async event => { event.preventDefault(); const data = new FormData(event.currentTarget); await save({ ...readParty(data, "seller"), vat_id: String(data.get("vat_id")), contact_name: String(data.get("contact_name")), phone: String(data.get("phone")), iban: String(data.get("iban")), invoice_prefix: String(data.get("invoice_prefix")), four_eyes: data.has("four_eyes") }); }}>
    <fieldset disabled={busy} className="space-y-5"><PartyFields prefix="seller" data={value} />
      <div className="grid gap-4 sm:grid-cols-2">{([['vat_id', 'Umsatzsteuer-ID', 11], ['contact_name', 'Ansprechpartner', 100], ['phone', 'Telefon', 40], ['iban', 'Deutsche IBAN', 35], ['invoice_prefix', 'Rechnungspräfix', 10]] as const).map(([key, label, max]) => <label className="text-sm" key={key}>{label}<input className={field} name={key} defaultValue={value?.[key]} maxLength={max} placeholder={key === "invoice_prefix" ? "z. B. RE" : undefined} pattern={key === "invoice_prefix" ? "[A-Z][A-Z0-9]{1,9}" : key === "vat_id" ? "DE[0-9]{9}" : undefined} required /></label>)}</div>
      <label className="flex min-h-11 items-start gap-3 text-sm"><input name="four_eyes" type="checkbox" defaultChecked={value?.four_eyes ?? true} className="mt-1" /><span>Vier-Augen-Prüfung erforderlich<span className="mt-1 block text-slate-600">Eine andere Person mit Finanzprüfrecht muss den Entwurf freigeben. Bei deaktivierter Regel kann eine berechtigte Person selbst prüfen; jede Freigabe bleibt ausdrücklich.</span></span></label>
      <p className="text-sm text-slate-600">Der Aussteller ist die Firma, die die Leistung abrechnet. Änderungen machen offene Freigaben ungültig. Ein bereits verwendetes Rechnungspräfix bleibt fest.</p>
      <button className={primary}>{busy ? "Speichern …" : value ? "Aussteller speichern" : "Aussteller anlegen"}</button>
    </fieldset>
  </form>;
}

const newLine = (): InvoiceLine => ({ description: "", quantity: "1", unit: "HUR", unit_price: "", vat_rate: 19 });
export function InvoiceForm({ value, busy, save, cancel }: { value?: Invoice; busy: boolean; save: (data: InvoiceInput, key: string) => Promise<void>; cancel: () => void }) {
  const source = value?.payload.invoice;
  const [lines, setLines] = useState<InvoiceLine[]>(source?.lines ?? [newLine()]);
  const request = useRef<{ fingerprint: string; key: string } | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const data: InvoiceInput = { buyer: readParty(form, "buyer"), buyer_reference: String(form.get("buyer_reference")), service_reference: String(form.get("service_reference")), issue_date: String(form.get("issue_date")), due_date: String(form.get("due_date")), service_start: String(form.get("service_start")), service_end: String(form.get("service_end")), currency: "EUR", lines };
    const fingerprint = JSON.stringify(data);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() };
    await save(data, request.current!.key);
  }
  return <form onSubmit={submit} className={`${box} space-y-5`} aria-label="Rechnungsentwurf"><h2 className="text-xl font-semibold">{value ? "Entwurf bearbeiten" : "Neue Rechnung vorbereiten"}</h2>
    <fieldset disabled={busy} className="space-y-6"><section className="space-y-3"><h3 className="font-semibold">Rechnungsempfänger</h3><PartyFields prefix="buyer" data={source?.buyer} /></section>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">Käuferreferenz<input className={field} name="buyer_reference" aria-label="Käuferreferenz" defaultValue={source?.buyer_reference} maxLength={120} required /><span className="mt-1 block text-xs text-slate-600">Mit dem Empfänger abgestimmte Referenz, bei Behörden gegebenenfalls Leitweg-ID.</span></label><label className="text-sm">Eindeutige Leistungsreferenz<input className={field} name="service_reference" aria-label="Eindeutige Leistungsreferenz" defaultValue={source?.service_reference} maxLength={120} required /><span className="mt-1 block text-xs text-slate-600">Zum Beispiel Auftrag und Abrechnungsperiode. Dieselbe Referenz kann je Aussteller nur einmal abgerechnet werden.</span></label>
        {([['issue_date', 'Rechnungsdatum'], ['due_date', 'Fällig am'], ['service_start', 'Leistungsbeginn'], ['service_end', 'Leistungsende']] as const).map(([key, label]) => <label className="text-sm" key={key}>{label}<input className={field} type="date" name={key} defaultValue={source?.[key] ?? today()} required /></label>)}
      </div>
      <section className="space-y-3"><h3 className="font-semibold">Leistungspositionen</h3><p className="text-sm text-slate-600">EUR · 19 % Umsatzsteuer. Mengen und Preise als Nettowerte eingeben. Die verbindliche Berechnung erscheint nach dem Speichern.</p>
        {lines.map((line, index) => <div key={index} className="grid gap-3 rounded-xl border bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4"><label className="text-sm sm:col-span-2 lg:col-span-4">Leistung<input aria-label={`Leistung ${index + 1}`} className={field} value={line.description} maxLength={500} onChange={e => setLines(rows => rows.map((r, i) => i === index ? { ...r, description: e.target.value } : r))} required /></label><label className="text-sm">Menge<input aria-label={`Menge ${index + 1}`} className={field} type="number" min="0.0001" max="1000000" step="0.0001" value={line.quantity} onChange={e => setLines(rows => rows.map((r, i) => i === index ? { ...r, quantity: e.target.value } : r))} required /></label><label className="text-sm">Einheit<select aria-label={`Einheit ${index + 1}`} className={field} value={line.unit} onChange={e => setLines(rows => rows.map((r, i) => i === index ? { ...r, unit: e.target.value as InvoiceLine["unit"] } : r))}><option value="HUR">Stunden</option><option value="C62">Stück / Pauschale</option></select></label><label className="text-sm">Nettopreis je Einheit<input aria-label={`Nettopreis ${index + 1}`} className={field} type="number" min="0.000001" max="10000000" step="0.000001" value={line.unit_price} onChange={e => setLines(rows => rows.map((r, i) => i === index ? { ...r, unit_price: e.target.value } : r))} required /></label><button type="button" aria-label={`Position ${index + 1} entfernen`} className={`${button} self-end`} disabled={lines.length === 1} onClick={() => setLines(rows => rows.filter((_, i) => i !== index))}>Entfernen</button></div>)}
        <button type="button" className={button} disabled={lines.length >= 100} onClick={() => setLines(rows => [...rows, newLine()])}>Position hinzufügen</button>
      </section>
      <div className="flex flex-wrap gap-3"><button className={primary}>{busy ? "Speichern …" : "Entwurf speichern"}</button><button type="button" className={button} onClick={cancel}>Schließen</button></div>
    </fieldset>
  </form>;
}
