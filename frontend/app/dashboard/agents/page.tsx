"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { recruiterApi, type JobPosting } from "@/lib/api";
import { agentApi, type AgentInput, type AgentOptions, type AgentRun, type ManagedAgent } from "@/lib/agents";
import { Button } from "@/components/ui/button";
import { AgentRunDetails } from "@/components/recruiter/AgentRunDetails";

const capabilities = { job_check: "Stellenangaben prüfen · Regeln", onboarding_draft: "Onboarding vorbereiten · Vorlage", ai_job_brief: "Stelle zusammenfassen · KI-Dienst" };
const states: Record<string, string> = { queued: "Eingeplant", running: "In Arbeit", awaiting_review: "Prüfung erforderlich", approved: "Freigegeben", rejected: "Verworfen", cancelled: "Abgebrochen", blocked: "Gesperrt", failed: "Fehlgeschlagen" };
const field = "mt-1 block min-w-0 w-full max-w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm";
const blank: AgentInput = { name: "", owner_id: "", enabled: false, capability: "job_check", daily_task_limit: 20, max_attempts: 3, four_eyes: true };

export default function AgentsPage() {
  const [options, setOptions] = useState<AgentOptions | null>(null);
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [form, setForm] = useState<AgentInput>(blank);
  const [editing, setEditing] = useState<ManagedAgent | null>(null);
  const [agentId, setAgentId] = useState("");
  const [jobId, setJobId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [authorizeAI, setAuthorizeAI] = useState(false);
  const [requestKey, setRequestKey] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const selected = agents.find(agent => agent.id === agentId);
  const load = useCallback(async () => {
    const token = auth.getAccess(); if (!token) return;
    const [members, registry, tasks, vacancies] = await Promise.all([agentApi.options(token), agentApi.list(token), agentApi.runs(token), recruiterApi.listJobs(token, 1, 100)]);
    setOptions(members); setAgents(registry); setRuns(tasks); setJobs(vacancies.jobs.filter(job => job.publication_status !== "archived"));
  }, []);
  useEffect(() => {
    let active = true;
    const refresh = () => load().catch(e => { if (active) setError(e instanceof Error ? e.message : "Daten konnten nicht geladen werden."); });
    void refresh();
    const timer = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [load]);

  async function action(work: (token: string) => Promise<unknown>, success: string) {
    const token = auth.getAccess(); if (!token) return false;
    setBusy(true); setError(""); setMessage("");
    try { await work(token); await load(); setMessage(success); return true; }
    catch (e) { setError(e instanceof Error ? e.message : "Änderung fehlgeschlagen."); return false; }
    finally { setBusy(false); }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (await action(token => editing ? agentApi.update(token, editing, form) : agentApi.create(token, form), "Agentenkonfiguration gespeichert.")) { setEditing(null); setForm(blank); }
  }
  async function assign(event: React.FormEvent) {
    event.preventDefault(); if (!selected) return;
    const key = requestKey || crypto.randomUUID(); setRequestKey(key);
    if (await action(token => agentApi.assign(token, selected, { job_id: jobId, reviewer_id: reviewer, title, instructions, authorize_ai: authorizeAI, request_key: key }), "Aufgabe eingeplant. Das Ergebnis wartet anschließend auf menschliche Prüfung.")) {
      setRequestKey(""); setTitle(""); setInstructions(""); setAuthorizeAI(false);
    }
  }
  function edit(agent: ManagedAgent) {
    setEditing(agent); setForm({ name: agent.name, owner_id: agent.owner_id || "", enabled: agent.enabled, capability: agent.capability, daily_task_limit: agent.daily_task_limit, max_attempts: agent.max_attempts, four_eyes: agent.four_eyes });
  }
  return <div className="mx-auto max-w-6xl space-y-6 px-4 pt-8 pb-40">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-bold">Agenten & Aufgaben</h1><Button variant="outline" disabled={busy} onClick={() => action(() => load(), "Aktualisiert.")}>Aktualisieren</Button></div>
    <p className="max-w-3xl text-sm text-gray-700">Verwalte digitale Assistenten mit eigener Verantwortung, begrenzten Aufgaben und menschlicher Prüfung. Regeln und Vorlagen sind als solche gekennzeichnet; die KI-Zusammenfassung benötigt einen eingerichteten und ausdrücklich freigegebenen KI-Dienst.</p>
    <div className="flex flex-wrap gap-4 text-sm text-blue-700"><Link href="/dashboard/processes" className="underline">Prozesse konfigurieren</Link><Link href="/dashboard/zeitarbeit/tasks" className="underline">Gemeinsame Aufgabenübersicht</Link></div>
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-red-800">{error}</p>}
    {message && <p role="status" className="rounded-md bg-green-50 p-3 text-green-800">{message}</p>}
    <section aria-label="Agentenverzeichnis" className="space-y-3">
      <h2 className="text-lg font-semibold">Agenten im Unternehmen</h2>
      {options && !agents.length && <p className="text-sm text-gray-600">Noch keine Agenten konfiguriert.</p>}
      <div className="grid gap-3 md:grid-cols-2">{agents.map(agent => <article key={agent.id} className="space-y-2 rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="font-semibold break-words">{agent.name}</h3>
        <p className="text-sm text-gray-700">{capabilities[agent.capability]} · {agent.enabled ? "Aktiv" : "Pausiert"} · Version {agent.version}</p>
        <p className="text-sm text-gray-600">Verantwortlich: {options?.members.find(member => member.id === agent.owner_id)?.name || "Zugang prüfen"}. Maximal {agent.daily_task_limit} neue Aufgaben pro UTC-Tag, {agent.max_attempts} Ausführungsversuche je Aufgabe und eine gleichzeitige Ausführung.</p>
        {options?.can_manage && <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => edit(agent)}>Konfigurieren</Button>
          <Button size="sm" variant="outline" disabled={busy || !agent.owner_id} onClick={() => action(token => agentApi.update(token, agent, { name: agent.name, owner_id: agent.owner_id!, capability: agent.capability, daily_task_limit: agent.daily_task_limit, max_attempts: agent.max_attempts, four_eyes: agent.four_eyes, enabled: !agent.enabled }), agent.enabled ? "Agent pausiert. Laufende Ergebnisse werden vor der Übernahme erneut geprüft." : "Agent aktiviert. Frühere Aufträge bleiben an ihre ursprüngliche Version gebunden.")}>{agent.enabled ? "Pausieren" : "Aktivieren"}</Button>
        </div>}
      </article>)}</div>
    </section>
    <div className="grid items-start gap-6 lg:grid-cols-2">
      {options?.can_manage && <form onSubmit={save} className="min-w-0 space-y-4 rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold">{editing ? "Agent konfigurieren" : "Agent anlegen"}</h2>
        <label className="block text-sm">Agentenname<input required maxLength={120} className={field} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label className="block text-sm">Verantwortliche Person<select required className={field} value={form.owner_id} onChange={e => setForm({ ...form, owner_id: e.target.value })}><option value="">Bitte auswählen</option>{options.members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>
        <label className="block text-sm">Fähigkeit<select className={field} value={form.capability} onChange={e => setForm({ ...form, capability: e.target.value as AgentInput["capability"], max_attempts: e.target.value === "ai_job_brief" ? 1 : 3 })}>{Object.entries(capabilities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="block text-sm">Tägliches Auftragslimit<input type="number" min={1} max={1000} required className={field} value={form.daily_task_limit} onChange={e => setForm({ ...form, daily_task_limit: Number(e.target.value) })} /></label>
        <p className="text-xs text-gray-600">Das Limit zählt auch fehlgeschlagene Aufträge. Ein Euro-Kostenlimit ist noch nicht angebunden.</p>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.four_eyes} onChange={e => setForm({ ...form, four_eyes: e.target.checked })} />Andere Person muss das Ergebnis prüfen (Vier-Augen-Prinzip)</label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} />Agent für neue Aufgaben aktivieren</label>
        <p className="text-xs text-gray-600">Konfigurationsänderungen sperren die weitere Verarbeitung alter Aufträge. Beauftrage die geänderte Version erneut.</p>
        <div className="flex gap-2"><Button type="submit" disabled={busy}>Agent speichern</Button>{editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(blank); }}>Abbrechen</Button>}</div>
      </form>}
      <form onSubmit={assign} className="min-w-0 space-y-4 rounded-xl border border-gray-200 bg-white p-5" onChange={() => setRequestKey("")}>
        <h2 className="text-lg font-semibold">Aufgabe an Agent vergeben</h2>
        <label className="block text-sm">Ausführender Agent<select required className={field} value={agentId} onChange={e => { setAgentId(e.target.value); setAuthorizeAI(false); }}><option value="">Bitte auswählen</option>{agents.filter(agent => agent.enabled).map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
        <label className="block text-sm">Stelle für den Auftrag<select required className={field} value={jobId} onChange={e => setJobId(e.target.value)}><option value="">Bitte auswählen</option>{jobs.map(job => <option key={job.id} value={job.id}>{job.title}</option>)}</select></label>
        <label className="block text-sm">Aufgabentitel<input required maxLength={300} className={field} value={title} onChange={e => setTitle(e.target.value)} /></label>
        <label className="block text-sm">Hinweise für die Prüfung<textarea maxLength={3000} rows={3} className={field} value={instructions} onChange={e => setInstructions(e.target.value)} /></label>
        <p className="text-xs text-gray-600">Regel- und Vorlagenassistenten führen ihre feste Fähigkeit aus. Freitext erweitert ihre Rechte nicht; die Hinweise bleiben für die menschliche Prüfung erhalten.</p>
        <label className="block text-sm">Verantwortlich für die Ergebnisprüfung<select required className={field} value={reviewer} onChange={e => setReviewer(e.target.value)}><option value="">Bitte auswählen</option>{options?.members.filter(member => !selected?.four_eyes || member.id !== options.current_user_id).map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>
        {selected?.capability === "ai_job_brief" && <label className="flex items-start gap-2 text-sm"><input type="checkbox" required checked={authorizeAI} onChange={e => setAuthorizeAI(e.target.checked)} />Ich gebe Stellendaten und Hinweise für den eingerichteten KI-Dienst frei. Bei unklarer Zustellung erfolgt keine automatische Wiederholung.</label>}
        {selected?.capability === "ai_job_brief" && !options?.external_ai_enabled && <p className="text-sm text-amber-800">Externe Agenten-KI benötigt zunächst die Freigabe und Einrichtung durch den Betreiber.</p>}
        <Button type="submit" disabled={busy || !selected || (selected.capability === "ai_job_brief" && !options?.external_ai_enabled)}>Aufgabe beauftragen</Button>
      </form>
    </div>
    <section aria-label="Agentenaufträge" className="space-y-4">
      <h2 className="text-lg font-semibold">Aufträge und Ergebnisse</h2>
      {runs.length === 0 && <p className="text-sm text-gray-600">Noch keine Agentenaufträge vorhanden.</p>}
      {runs.map(run => <article key={run.id} className="space-y-3 rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="font-semibold break-words">{run.source.task_title} · {states[run.status] || run.status}</h3>
        <p className="text-sm text-gray-600">{agents.find(agent => agent.id === run.agent_id)?.name} · {run.source.title} · Versuch {run.attempts}/{run.max_attempts}</p>
        {run.source.instructions && <p className="whitespace-pre-wrap break-words text-sm">Prüfhinweise: {run.source.instructions}</p>}
        {run.output && <><p className="text-xs font-medium text-gray-600">Ergebnis aus {run.output_origin === "ai" ? `KI · ${run.provider_model}` : run.output_origin === "rule" ? "Regelprüfung" : "Vorlage"}</p><p className="whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-4 text-sm">{run.output}</p></>}
        {["failed", "blocked"].includes(run.status) && <p className="text-sm text-amber-800">Der Auftrag konnte nicht abgeschlossen werden. Prüfe Agentenstatus, Zugänge und Stellenversion; anschließend kann ein neuer Auftrag angelegt werden.</p>}
        {run.status === "awaiting_review" && run.reviewer_id === options?.current_user_id && <div className="space-y-3">
          <label className="block text-sm">Prüfvermerk<textarea maxLength={2000} className={field} value={notes[run.id] || ""} onChange={e => setNotes({ ...notes, [run.id]: e.target.value })} /></label>
          <div className="flex flex-wrap gap-2"><Button disabled={busy || (notes[run.id] || "").trim().length < 5} onClick={() => action(token => agentApi.review(token, run, "approve", notes[run.id]), "Ergebnis freigegeben; Aufgabe abgeschlossen.")}>Ergebnis freigeben</Button><Button variant="outline" disabled={busy || (notes[run.id] || "").trim().length < 5} onClick={() => action(token => agentApi.review(token, run, "reject", notes[run.id]), "Ergebnis verworfen.")}>Ergebnis verwerfen</Button></div>
        </div>}
        {run.review_note && <p className="text-sm text-gray-700">Prüfvermerk: {run.review_note}</p>}
        <AgentRunDetails run={run} members={options?.members || []} />
        {!["approved", "rejected", "cancelled"].includes(run.status) && (options?.can_manage || [run.delegated_by, run.reviewer_id].includes(options?.current_user_id || "")) && <Button variant="outline" disabled={busy} onClick={() => action(token => agentApi.cancel(token, run), "Auftrag abgebrochen.")}>Auftrag abbrechen</Button>}
      </article>)}
    </section>
  </div>;
}
