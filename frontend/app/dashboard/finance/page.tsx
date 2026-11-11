"use client";

import { useEffect, useRef, useState } from "react";
import { FileCheck2, FilePlus2, Receipt, ShieldCheck, RefreshCw } from "lucide-react";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { financeApi, invoiceStates, permissionNames, euro, today, type Entity, type Grant, type Invoice, type FinanceEvent, type Permission } from "@/lib/finance";
import { EntityForm, InvoiceForm, box, button, field, primary } from "@/components/finance/FinanceForms";

const eventNames: Record<string, string> = { draft_created: "Entwurf angelegt", draft_updated: "Entwurf geändert", submitted: "Zur Prüfung vorgelegt", approved: "Fachlich freigegeben", returned: "Zur Bearbeitung zurückgegeben", validation_failed: "Formatprüfung fehlgeschlagen", finalized: "Finalisiert", credit_draft_created: "Stornobeleg vorbereitet", cancelled: "Durch Stornobeleg aufgehoben" };

export default function FinancePage() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [entityId, setEntityId] = useState("");
  const [rows, setRows] = useState<Invoice[]>([]);
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [events, setEvents] = useState<FinanceEvent[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [tab, setTab] = useState("invoices");
  const [form, setForm] = useState<"new" | "edit" | null>(null);
  const [newEntity, setNewEntity] = useState(false);
  const [note, setNote] = useState("");
  const [creditDate, setCreditDate] = useState(today);
  const [isAdmin, setIsAdmin] = useState(false);
  const [userId, setUserId] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const creditRequest = useRef<{ fingerprint: string; key: string } | null>(null);
  const entity = entities.find(e => e.id === entityId);
  const can = (permission: Permission) => entity?.permissions.includes(permission) ?? false;
  const token = () => auth.getAccess()!;

  useEffect(() => {
    let active = true; const t = auth.getAccess(); if (!t) return;
    Promise.all([financeApi.entities(t), authApi.me(t)]).then(([list, user]) => {
      if (!active) return;
      setEntities(list); setEntityId(list[0]?.id ?? ""); setIsAdmin(user.role === "admin"); setUserId(user.id);
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!entityId) return; let active = true;
    financeApi.invoices(token(), entityId, offset).then(list => { if (active) setRows(list); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [entityId, offset]);
  useEffect(() => {
    if (tab !== "grants" || !entityId) return; let active = true;
    financeApi.grants(token(), entityId).then(list => { if (active) setGrants(list); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [tab, entityId]);
  useEffect(() => {
    if (!selected) return; let active = true;
    financeApi.events(token(), selected.id).then(list => { if (active) setEvents(list); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selected]);

  function choose(id: string) {
    setEntityId(id); setRows([]); setSelected(null); setEvents([]); setGrants([]); setForm(null); setTab("invoices"); setOffset(0); setNote(""); setError(""); setMessage(""); setNewEntity(false);
  }
  async function perform(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Aktion fehlgeschlagen."); } finally { setBusy(false); }
  }
  async function refresh(saved?: Invoice) {
    setRows(await financeApi.invoices(token(), entityId, offset));
    if (saved) { setSelected(saved); setNote(""); }
    else if (selected) setSelected(await financeApi.invoice(token(), selected.id));
  }
  function decide(action: string) {
    if (!selected) return;
    void perform(async () => {
      const invoice = await financeApi.decision(token(), selected, action, note);
      await refresh(invoice);
      if (invoice.validation?.status === "invalid") setError(`Formatprüfung fehlgeschlagen: ${invoice.validation.errors.join(", ") || "Bitte Prüfbericht ansehen"}. Die Rechnung wurde nicht finalisiert.`);
      else setMessage(action === "finalize" ? `Rechnung ${invoice.number} finalisiert. Noch nicht versendet.` : `Rechnungsstand: ${invoiceStates[invoice.status]}.`);
    });
  }
  const scopeNote = "Inländische Leistungsrechnungen in EUR mit 19 % Umsatzsteuer. Sondersteuerfälle, ZUGFeRD, Peppol-Versand und DATEV/ELSTER folgen als gesonderte Anbindungen.";
  return <div className="mx-auto max-w-7xl space-y-6 p-4 md:p-8">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="mb-2 text-sm font-medium text-blue-700">Von der Leistung zur geprüften Rechnung</p><h1 className="text-3xl font-semibold tracking-tight">Finanzen & Rechnungen</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Leistungen nachvollziehbar abrechnen, gemeinsam prüfen und als XRechnung bereitstellen.</p></div>{isAdmin && <button className={button} disabled={busy} onClick={() => { setNewEntity(true); setTab("issuer"); }}>Rechnungsaussteller hinzufügen</button>}</header>
    {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">{error}</p>}
    {message && <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{message}</p>}
    {loading && <p role="status">Finanzarbeitsbereich wird geladen …</p>}
    {!loading && !entities.length && !newEntity && <section className={`${box} max-w-3xl space-y-4`}><Receipt aria-hidden="true" className="text-blue-700" /><h2 className="text-xl font-semibold">Ein eigener Bereich für Ihre Rechnungen</h2><p className="text-sm leading-6 text-slate-600">{isAdmin ? "Legen Sie Ihre Firma als Rechnungsaussteller mit Anschrift, Umsatzsteuer-ID und Zahlungsdaten an. Danach vergeben Sie gezielt Finanzrechte an Ihre Kollegen." : "Für Ihr Konto wurde noch kein Rechnungsaussteller freigegeben. Die zuständige Finanzverwaltung kann Ihnen die benötigten Rechte geben."}</p><p className="text-sm text-slate-600">{scopeNote}</p>{isAdmin && <button className={primary} onClick={() => { setNewEntity(true); setTab("issuer"); }}>Ersten Aussteller anlegen</button>}</section>}
    {!!entities.length && <div className="flex flex-wrap items-end gap-4"><label className="min-w-0 flex-1 text-sm sm:max-w-md">Rechnungsaussteller<select className={field} value={entityId} disabled={busy} onChange={e => choose(e.target.value)}>{entities.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label><button aria-label="Finanzbereich aktualisieren" className={button} disabled={busy} onClick={() => void perform(async () => { setEntities(await financeApi.entities(token())); await refresh(); setMessage("Finanzbereich aktualisiert."); })}><RefreshCw size={18} aria-hidden="true" /></button></div>}
    {entity && <nav aria-label="Finanzansichten" className="flex flex-wrap gap-2 border-b pb-4">{[['invoices', 'Rechnungen', true], ['issuer', 'Ausstellerdaten', can("manage")], ['grants', 'Finanzrechte', can("manage")]].filter(([, , show]) => show).map(([key, label]) => <button key={String(key)} disabled={busy} aria-pressed={tab === key} className={tab === key ? primary : button} onClick={() => { setTab(String(key)); setNewEntity(false); }}>{label}</button>)}</nav>}
    {tab === "issuer" && (newEntity || entity && can("manage")) && <section className={`${box} max-w-4xl space-y-5`}><h2 className="text-xl font-semibold">{newEntity ? "Rechnungsaussteller einrichten" : "Ausstellerdaten"}</h2><EntityForm key={newEntity ? "new" : `${entityId}-${entity?.version}`} value={newEntity ? undefined : entity} busy={busy} save={data => perform(async () => { const saved = await financeApi.entity(token(), data, newEntity ? undefined : entity); const list = await financeApi.entities(token()); setEntities(list); choose(saved.id); setMessage("Rechnungsaussteller gespeichert."); })} /></section>}
    {tab === "grants" && entity && can("manage") && <section className={`${box} space-y-5`}><div className="flex items-center gap-3"><ShieldCheck aria-hidden="true" className="text-blue-700" /><h2 className="text-xl font-semibold">Finanzrechte pro Person</h2></div><p className="max-w-3xl text-sm leading-6 text-slate-600">Diese Rechte gelten ausschließlich für {entity.name}. Vorbereiten, Prüfen, Finalisieren und Exportieren sind getrennt. Eine Firmenkooperation gibt keinen Zugriff auf Finanzdaten.</p>{grants.map(g => <article key={g.user_id} className="space-y-4 rounded-xl border p-4"><h3 className="font-semibold">{g.name}</h3><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(permissionNames).map(([key, label]) => <label key={key} className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" aria-label={`${label} für ${g.name}`} checked={g.permissions.includes(key as Permission)} disabled={busy} onChange={e => setGrants(list => list.map(row => row.user_id === g.user_id ? { ...row, permissions: e.target.checked ? [...row.permissions, key as Permission] : row.permissions.filter(p => p !== key) } : row))} />{label}</label>)}</div><button className={button} disabled={busy} onClick={() => void perform(async () => { const saved = await financeApi.grant(token(), entity.id, g); setGrants(list => list.map(row => row.user_id === g.user_id ? saved : row)); setEntities(await financeApi.entities(token())); setMessage(`Finanzrechte für ${g.name} gespeichert.`); })}>Rechte für {g.name} speichern</button></article>)}</section>}
    {tab === "invoices" && entity && <>
      <div className="grid gap-4 sm:grid-cols-3">{[{ icon: FilePlus2, label: "In Vorbereitung", count: rows.filter(i => i.status === "draft").length }, { icon: ShieldCheck, label: "Warten auf Prüfung", count: rows.filter(i => i.status === "in_review").length }, { icon: FileCheck2, label: "Finalisiert", count: rows.filter(i => i.status === "finalized").length }].map(item => <div key={item.label} className={box}><item.icon size={20} className="mb-3 text-blue-700" aria-hidden="true" /><p className="text-3xl font-semibold">{item.count}</p><p className="mt-1 text-sm text-slate-600">{item.label} · angezeigte Belege</p></div>)}</div>
      <section className={`${box} space-y-4`}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Rechnungsübersicht</h2>{can("prepare") && <button className={primary} disabled={busy} onClick={() => { setForm("new"); setSelected(null); setNote(""); }}>Neue Rechnung</button>}</div><p className="text-sm text-slate-600">{scopeNote}</p>{!rows.length && <p className="py-6 text-sm text-slate-600">Noch keine Rechnungen in dieser Ansicht.</p>}<ul className="divide-y">{rows.map(i => <li key={i.id}><button aria-pressed={selected?.id === i.id} className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl px-3 py-4 text-left hover:bg-slate-50 disabled:opacity-50" disabled={busy} onClick={() => { setSelected(i); setEvents([]); setForm(null); setNote(""); }}><span className="min-w-0"><span className="block font-semibold">{i.number ?? "Entwurf"} · {i.buyer_name}</span><span className="mt-1 block break-words text-xs text-slate-600">{i.service_reference}{i.kind === "credit_note" ? " · Stornobeleg" : ""}</span></span><span className="text-right"><span className="block font-semibold">{i.kind === "credit_note" ? "−" : ""}{euro(i.total)}</span><span className="mt-1 block text-xs text-slate-600">{invoiceStates[i.status]}</span></span></button></li>)}</ul><div className="flex flex-wrap items-center gap-3"><button className={button} disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 50))}>Vorherige</button><span className="text-xs text-slate-600">Seite {offset / 50 + 1} · bis zu 50 Belege</span><button className={button} disabled={busy || rows.length < 50} onClick={() => setOffset(n => n + 50)}>Weitere</button></div></section>
      {form && can("prepare") && <InvoiceForm key={form === "new" ? `new-${entity.id}` : `${selected?.id}-${selected?.version}`} value={form === "edit" ? selected ?? undefined : undefined} busy={busy} cancel={() => setForm(null)} save={(data, key) => perform(async () => { const saved = await financeApi.save(token(), entity.id, data, key, form === "edit" ? selected ?? undefined : undefined); setForm(null); await refresh(saved); setMessage("Rechnungsentwurf gespeichert. Beträge wurden berechnet."); })} />}
      {selected && !form && <section className={`${box} space-y-6`} aria-labelledby="invoice-detail"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 id="invoice-detail" className="text-xl font-semibold">{selected.kind === "credit_note" ? "Stornobeleg" : "Rechnung"} {selected.number ?? "ohne Nummer"}</h2><p className="mt-2 text-sm text-slate-600">{invoiceStates[selected.status]} · Version {selected.version} · {selected.issue_date}</p>{selected.payload.original_number && <p className="mt-2 text-sm">Bezug: {selected.payload.original_number}</p>}</div><p className="text-2xl font-semibold">{selected.kind === "credit_note" ? "−" : ""}{euro(selected.total)}</p></div>
        <div className="grid gap-4 sm:grid-cols-2">{[['Aussteller', selected.payload.seller], ['Empfänger', selected.payload.invoice.buyer]].map(([label, value]) => { const p = value as Entity; return <div key={String(label)} className="rounded-xl bg-slate-50 p-4"><h3 className="mb-2 text-sm font-semibold">{String(label)}</h3><p className="break-words text-sm leading-6">{p.name}<br />{p.street}<br />{p.postal_code} {p.city}<br />{p.email}</p></div>; })}</div>
        <dl className="grid gap-4 text-sm sm:grid-cols-2"><div><dt className="text-slate-600">Leistungszeitraum</dt><dd className="mt-1">{selected.payload.invoice.service_start} bis {selected.payload.invoice.service_end}</dd></div><div><dt className="text-slate-600">Fälligkeit</dt><dd className="mt-1">{selected.payload.invoice.due_date}</dd></div><div><dt className="text-slate-600">Käuferreferenz</dt><dd className="mt-1 break-words">{selected.payload.invoice.buyer_reference}</dd></div><div><dt className="text-slate-600">Leistungsreferenz</dt><dd className="mt-1 break-words">{selected.service_reference}</dd></div></dl>
        <div><h3 className="mb-3 font-semibold">Leistungen und Beträge</h3><ol className="divide-y rounded-xl border px-4">{selected.payload.invoice.lines.map((line, i) => <li key={i} className="space-y-1 py-3 text-sm"><p className="font-medium">{i + 1}. {line.description}</p><p className="text-slate-600">{line.quantity} {line.unit === "HUR" ? "Stunden" : "Stück"} × {line.unit_price} EUR netto · 19 % USt.</p></li>)}</ol><dl className="ml-auto mt-4 max-w-sm space-y-2 text-sm">{[['Netto', selected.payload.totals.net], ['Umsatzsteuer 19 %', selected.payload.totals.tax], ['Gesamt', selected.payload.totals.gross]].map(([label, amount]) => <div className="flex justify-between gap-4" key={label}><dt>{label}</dt><dd className="font-semibold">{euro(amount)}</dd></div>)}</dl></div>
        <details className="rounded-xl border p-4"><summary className="cursor-pointer font-medium">Zahlungsdaten und Nachweise</summary><dl className="mt-4 space-y-3 text-sm"><div><dt>Umsatzsteuer-ID</dt><dd>{selected.payload.seller.vat_id}</dd></div><div><dt>IBAN</dt><dd className="break-all">{selected.payload.seller.iban}</dd></div><div><dt>Prüfsumme des Datenstands</dt><dd className="break-all font-mono text-xs">{selected.payload_hash}</dd></div>{selected.artifact_hash && <div><dt>Prüfsumme der XRechnung</dt><dd className="break-all font-mono text-xs">{selected.artifact_hash}</dd></div>}</dl></details>
        {selected.validation && <div className={`rounded-xl p-4 text-sm ${selected.validation.status === "valid" ? "bg-emerald-50 text-emerald-950" : "bg-amber-50 text-amber-950"}`}><p className="font-semibold">{selected.validation.status === "valid" ? "XRechnungsprüfung bestanden" : "XRechnungsprüfung fehlgeschlagen"}</p><p className="mt-1">{selected.validation.validator} · {selected.validation.rules}</p>{selected.validation.errors.length > 0 && <p className="mt-2 break-words">{selected.validation.errors.join(", ")}</p>}</div>}
        {!["finalized", "cancelled"].includes(selected.status) && <div className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/40 p-4"><h3 className="font-semibold">Nächster Schritt</h3><label className="block text-sm">Prüfvermerk<textarea className={field} value={note} maxLength={1000} onChange={e => setNote(e.target.value)} rows={3} /></label><div className="flex flex-wrap gap-3">
          {selected.status === "draft" && can("prepare") && <>{selected.kind === "invoice" && <button className={button} disabled={busy} onClick={() => setForm("edit")}>Entwurf bearbeiten</button>}<button className={primary} disabled={busy || note.trim().length < 3} onClick={() => decide("submit")}>Zur Prüfung vorlegen</button></>}
          {selected.status === "in_review" && can("approve") && <button className={primary} disabled={busy || note.trim().length < 3 || entity.four_eyes && selected.prepared_by === userId} onClick={() => decide("approve")}>Fachlich freigeben</button>}
          {selected.status === "approved" && can("issue") && <button className={primary} disabled={busy || note.trim().length < 3} onClick={() => decide("finalize")}>{busy ? "Formatprüfung läuft …" : "Prüfen & finalisieren"}</button>}
          {["approved", "in_review"].includes(selected.status) && (can("prepare") || can("approve")) && <button className={button} disabled={busy || note.trim().length < 3} onClick={() => decide("return")}>Zur Bearbeitung zurückgeben</button>}
        </div><p className="text-xs leading-5 text-slate-600">{entity.four_eyes ? "Vier-Augen-Prüfung aktiv. Eine andere berechtigte Person muss den Entwurf freigeben. " : "Ausdrückliche Selbstprüfung ist für diesen Aussteller erlaubt. "}Die endgültige Nummer wird erst nach erfolgreicher Formatprüfung vergeben. Die Finalisierung versendet keine Rechnung.</p></div>}
        {can("export") && <div className="flex flex-wrap gap-3">{selected.artifact_hash && <button className={primary} disabled={busy} onClick={() => void perform(() => financeApi.download(token(), selected))}>XRechnung herunterladen</button>}{selected.validation && <button className={button} disabled={busy} onClick={() => void perform(() => financeApi.download(token(), selected, true))}>Prüfbericht herunterladen</button>}</div>}
        {selected.status === "finalized" && selected.kind === "invoice" && can("prepare") && <details className="rounded-xl border p-4"><summary className="cursor-pointer font-medium">Rechnung vollständig stornieren</summary><p className="my-3 text-sm text-slate-600">Es entsteht ein eigener Stornobeleg über den gesamten Betrag, der erneut geprüft und finalisiert werden muss. Die Originaldatei bleibt erhalten.</p><label className="block text-sm">Stornodatum<input className={`${field} max-w-xs`} type="date" min={selected.issue_date} value={creditDate} onChange={e => setCreditDate(e.target.value)} /></label><label className="mt-3 block text-sm">Stornogrund<textarea className={field} value={note} maxLength={1000} onChange={e => setNote(e.target.value)} /></label><button className={`${button} mt-3`} disabled={busy || note.trim().length < 3 || !creditDate} onClick={() => void perform(async () => { const fingerprint = JSON.stringify([selected.id, note, creditDate]); if (creditRequest.current?.fingerprint !== fingerprint) creditRequest.current = { fingerprint, key: crypto.randomUUID() }; const saved = await financeApi.credit(token(), selected, note, creditDate, creditRequest.current!.key); await refresh(saved); setMessage("Stornobeleg zur Prüfung vorbereitet."); })}>Stornobeleg vorbereiten</button></details>}
        <section><h3 className="font-semibold">Rechnungsverlauf</h3><ol className="mt-3 space-y-3 text-sm">{events.map((event, i) => <li key={i} className="border-l-2 border-slate-200 pl-3"><p>{eventNames[event.action] ?? event.action} · {new Date(event.created_at).toLocaleString("de-DE")}</p>{event.note && <p className="mt-1 whitespace-pre-wrap break-words text-slate-600">{event.note}</p>}</li>)}</ol></section>
      </section>}
    </>}
  </div>;
}
