"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { authApi, recruiterApi, type JobPosting } from "@/lib/api";
import { processApi, processActions, processStatuses, type ProcessInput, type ProcessTemplate, type ProcessRun, type ProcessStep, type ProcessAction } from "@/lib/processes";

const initial = (): ProcessInput => ({ name: "Stelle vorbereiten", enabled: false, four_eyes: true, steps: [
  { action: "job_check", title: "Vollständigkeit prüfen", text: "", mode: "automatic" },
  { action: "message_draft", title: "Ansprache vorbereiten", text: "Wir suchen Verstärkung für {title} bei {company} in {location}. Gerne geben wir Ihnen weitere Informationen zur Stelle.", mode: "review" },
] });
const field = "mt-1 min-h-11 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm disabled:bg-slate-100";
const button = "min-h-11 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium disabled:opacity-50";
const panel = "space-y-4 rounded-2xl border bg-white p-5";
const errorText = (e: unknown) => e instanceof Error ? e.message : "Die Aktion konnte nicht abgeschlossen werden.";

export default function ProcessesPage() {
  const [templates, setTemplates] = useState<ProcessTemplate[]>([]);
  const [runs, setRuns] = useState<ProcessRun[]>([]);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [userId, setUserId] = useState("");
  const [editing, setEditing] = useState<ProcessTemplate | null>(null);
  const [form, setForm] = useState<ProcessInput>(initial);
  const [selected, setSelected] = useState("");
  const [jobId, setJobId] = useState("");
  const [authorizeAI, setAuthorizeAI] = useState(false);
  const [active, setActive] = useState<ProcessRun | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const startKey = useRef<{ scope: string; key: string } | null>(null);
  async function reload() {
    const token = auth.getAccess(); if (!token) return;
    const [t, r, j, me] = await Promise.all([processApi.templates(token), processApi.runs(token), recruiterApi.listJobs(token, 1, 100), authApi.me(token)]);
    setTemplates(t); setRuns(r); setJobs(j.jobs); setIsAdmin(me.role === "admin"); setUserId(me.id);
  }
  useEffect(() => { reload().catch(e => setError(errorText(e))).finally(() => setLoading(false)); }, []);
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  function stepChange(index: number, patch: Partial<ProcessStep>) {
    setForm(f => ({ ...f, steps: f.steps.map((s, i) => {
      if (i !== index) return s;
      const result = { ...s, ...patch };
      if (["message_draft", "ai_job_brief"].includes(result.action)) result.mode = "review";
      return result;
    }) }));
  }
  const chosen = templates.find(t => t.id === selected);
  const requiresAI = chosen?.steps.some(s => s.action === "ai_job_brief");
  const canReview = active && (!active.four_eyes || active.created_by !== userId);
  return <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-2xl font-bold">Prozesse & Agenten</h1><p className="mt-2 text-sm text-slate-600">Vorarbeiten ausführen lassen, Ergebnisse prüfen und Abläufe nachvollziehen.</p></div><button className={button} disabled={busy} onClick={() => perform(async () => { await reload(); if (active) setActive(await processApi.detail(auth.getAccess()!, active.id)); })}>Neu laden</button></div>
    {error && <p role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4 text-red-900">{error}</p>}
    {message && <p role="status" className="rounded-xl bg-green-50 p-4 text-green-900">{message}</p>}
    <Link href="/dashboard/agents" className="text-sm text-blue-700 underline">Agenten verwalten und Aufgaben vergeben</Link>
    {loading && <p role="status">Prozesse werden geladen …</p>}
    <div className="grid gap-6 lg:grid-cols-2">
      <section aria-labelledby="process-config" className={panel}>
        <h2 id="process-config" className="text-lg font-semibold">Prozess konfigurieren</h2>
        {!isAdmin && <p className="text-sm text-slate-600">Die Firmenadministration verwaltet Vorlagen. HR kann aktivierte Prozesse starten und prüfen.</p>}
        <label className="block text-sm font-medium">Vorlage bearbeiten<select className={field} value={editing?.id ?? ""} disabled={!isAdmin || busy} onChange={e => { const p = templates.find(t => t.id === e.target.value); setEditing(p ?? null); setForm(p ? { name: p.name, enabled: p.enabled, four_eyes: p.four_eyes, steps: p.steps.map(s => ({ ...s })) } : initial()); }}><option value="">Neuer Prozess</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name} · Version {t.version}</option>)}</select></label>
        <form onSubmit={e => { e.preventDefault(); perform(async () => { const token = auth.getAccess()!; const saved = editing ? await processApi.update(token, editing.id, { ...form, version: editing.version }) : await processApi.create(token, form); setEditing(saved); await reload(); setSelected(saved.id); setMessage("Prozess gespeichert."); }); }}>
          <fieldset disabled={!isAdmin || busy} className="space-y-4">
            <label className="block text-sm font-medium">Prozessname<input className={field} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} maxLength={120} required /></label>
            <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} />Prozess aktivieren</label>
            <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={form.four_eyes} onChange={e => setForm({ ...form, four_eyes: e.target.checked })} />Vier-Augen-Prinzip: eine andere HR-Person prüft</label>
            <ol className="space-y-4">{form.steps.map((step, index) => <li key={index} className="space-y-3 rounded-xl border bg-slate-50 p-4">
              <p className="font-semibold">Schritt {index + 1}</p>
              <label className="block text-sm">Aktion<select aria-label={`Aktion Schritt ${index + 1}`} className={field} value={step.action} onChange={e => stepChange(index, { action: e.target.value as ProcessAction })}>{Object.entries(processActions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label className="block text-sm">Bezeichnung<input aria-label={`Bezeichnung Schritt ${index + 1}`} className={field} value={step.title} onChange={e => stepChange(index, { title: e.target.value })} maxLength={120} required /></label>
              <label className="block text-sm">Ausführung<select aria-label={`Ausführung Schritt ${index + 1}`} className={field} value={step.mode} onChange={e => stepChange(index, { mode: e.target.value as ProcessStep["mode"] })}><option value="review">Ergebnis prüfen</option>{!["message_draft", "ai_job_brief"].includes(step.action) && <option value="automatic">Automatisch</option>}</select></label>
              {["message_draft", "internal_notification"].includes(step.action) && <label className="block text-sm">Text<textarea aria-label={`Text Schritt ${index + 1}`} className={field} rows={4} value={step.text} onChange={e => stepChange(index, { text: e.target.value })} maxLength={2000} required /><span className="text-xs text-slate-600">Platzhalter: {"{title}, {company}, {location}"}. Nachrichten bleiben Entwürfe.</span></label>}
              {step.action === "ai_job_brief" && <p className="text-sm text-slate-600">Ein KI-Aufruf fasst Stellendaten zusammen. Danach ist eine Prüfung erforderlich.</p>}
              <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={index === 0} onClick={() => setForm(f => { const steps = [...f.steps]; [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]]; return { ...f, steps }; })}>Nach oben</button><button type="button" className={button} disabled={form.steps.length === 1} onClick={() => setForm(f => ({ ...f, steps: f.steps.filter((_, i) => i !== index) }))}>Schritt entfernen</button></div>
            </li>)}</ol>
            <div className="flex flex-wrap gap-3"><button type="button" className={button} disabled={form.steps.length >= 8} onClick={() => setForm(f => ({ ...f, steps: [...f.steps, { action: "job_check", title: "Stellenangaben prüfen", text: "", mode: "review" }] }))}>Schritt hinzufügen</button><button type="submit" className={button}>Prozess speichern</button></div>
          </fieldset>
        </form>
      </section>
      <div className="space-y-6"><section aria-labelledby="process-start" className={panel}>
        <h2 id="process-start" className="text-lg font-semibold">Prozess starten</h2>
        <form onSubmit={e => { e.preventDefault(); if (!chosen) return; perform(async () => { const scope = `${chosen.id}:${chosen.version}:${jobId}:${authorizeAI}`; if (startKey.current?.scope !== scope) startKey.current = { scope, key: crypto.randomUUID() }; setActive(await processApi.start(auth.getAccess()!, chosen, jobId, startKey.current.key, authorizeAI)); setNote(""); startKey.current = null; await reload(); }); }}>
          <fieldset disabled={busy} className="space-y-4">
            <label className="block text-sm font-medium">Aktiver Prozess<select className={field} required value={selected} onChange={e => { setSelected(e.target.value); setAuthorizeAI(false); }}><option value="">Bitte auswählen</option>{templates.filter(t => t.enabled).map(t => <option key={t.id} value={t.id}>{t.name} · Version {t.version}</option>)}</select></label>
            <label className="block text-sm font-medium">Stelle<select className={field} required value={jobId} onChange={e => setJobId(e.target.value)}><option value="">Bitte auswählen</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.title} · {j.company}</option>)}</select></label>
            {requiresAI && <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={authorizeAI} onChange={e => setAuthorizeAI(e.target.checked)} required />Ich gebe die Stellendaten für diesen KI-Lauf frei. Dienstleister und Rechtsgrundlage für enthaltene Daten sind geprüft.</label>}
            <button className={button} disabled={!chosen || !jobId || !!requiresAI && !authorizeAI}>Prozess starten</button>
          </fieldset>
        </form><p className="text-xs text-slate-600">Manueller Auslöser. Die Freigabe versendet keine Nachricht und ändert keine Bewerbungsentscheidung. KI ist nur mit eingerichtetem Dienst verfügbar.</p>
      </section><section aria-labelledby="process-runs" className={panel}><h2 id="process-runs" className="text-lg font-semibold">Letzte Läufe</h2>{!runs.length && !loading && <p className="text-sm text-slate-600">Noch keine Läufe vorhanden.</p>}<ul className="space-y-2">{runs.map(run => <li key={run.id}><button disabled={busy} onClick={() => perform(async () => { setActive(await processApi.detail(auth.getAccess()!, run.id)); setNote(""); })} className="w-full rounded-xl border p-3 text-left hover:bg-slate-50"><span className="block font-medium">{run.name}</span><span className="text-sm text-slate-600">{run.source.title} · {processStatuses[run.status] ?? run.status}</span></button></li>)}</ul></section></div>
    </div>
    {active && <section aria-labelledby="run-detail" className={panel}>
      <h2 id="run-detail" className="text-lg font-semibold">{active.name} · {processStatuses[active.status]}</h2>
      <p className="text-sm text-slate-600">{active.source.title} · Prozessversion {active.template_version} · {new Date(active.created_at).toLocaleString("de-DE")}</p>
      <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">Verwendete Stellendaten</summary><dl className="mt-3 space-y-2 text-sm">{Object.entries(active.source).map(([key, value]) => <div key={key}><dt className="font-medium">{({ title: "Stelle", company: "Unternehmen", description: "Beschreibung", location: "Arbeitsort", skills: "Anforderungen", salary_min: "Gehalt ab", salary_max: "Gehalt bis" } as Record<string, string>)[key] ?? key}</dt><dd className="whitespace-pre-wrap break-words">{value || "Nicht angegeben"}</dd></div>)}</dl></details>
      {active.results.map(result => <article key={result.step} className="rounded-xl bg-slate-50 p-4"><h3 className="font-semibold">{result.step + 1}. {result.title}</h3><p className="mt-1 text-xs text-slate-600">{result.origin === "ai" ? "KI-Ergebnis · sachlich prüfen" : "Regel / Vorlage"} · {processStatuses[result.status] ?? result.status}</p><p className="mt-3 whitespace-pre-wrap break-words text-sm">{result.output}</p></article>)}
      {["awaiting_review", "blocked"].includes(active.status) && <div className="space-y-3"><label className="block text-sm font-medium">Prüfvermerk<textarea className={field} value={note} onChange={e => setNote(e.target.value)} maxLength={2000} placeholder="Welche Angaben wurden geprüft?" /></label>{!canReview && active.status === "awaiting_review" && <p className="text-sm text-amber-900">Eine andere HR-Person muss diesen Lauf prüfen.</p>}<div className="flex flex-wrap gap-3">{(["approve", "reject", "cancel"] as const).map(decision => <button key={decision} className={button} disabled={busy || note.trim().length < 3 || decision !== "cancel" && (active.status !== "awaiting_review" || !canReview)} onClick={() => perform(async () => { setActive(await processApi.review(auth.getAccess()!, active, decision, note)); setNote(""); await reload(); })}>{decision === "approve" ? "Schritt freigeben" : decision === "reject" ? "Ablehnen" : "Lauf abbrechen"}</button>)}</div></div>}
      <h3 className="font-semibold">Verlauf</h3><ol className="space-y-2 text-sm">{active.events.map(e => <li key={e.id} className="border-l-2 border-slate-300 pl-3"><span className="text-slate-600">{new Date(e.created_at).toLocaleString("de-DE")} · </span>{({ started: "Gestartet", prepared: "Vorbereitet", approved: "Freigegeben", reject: "Abgelehnt", cancel: "Abgebrochen", completed: "Abgeschlossen", blocked: "Blockiert" } as Record<string, string>)[e.action] ?? e.action}{e.note && <p>{e.note}</p>}</li>)}</ol>
    </section>}
  </div>;
}
