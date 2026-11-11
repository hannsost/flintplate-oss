"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ClipboardCheck, Download, Plus, RefreshCw } from "lucide-react";
import { auth } from "@/lib/auth";
import { stockQuantity } from "@/lib/flintplate-inventory";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { message, venueApi, type Member, type Venue } from "@/lib/flintplate";
import { Empty, Field, Modal, Tag } from "./shared";

type Settings = { name: string; location: string; instructions: string; minimum: string; maximum: string; unit: string; interval_minutes: number; responsible_user_id: string; active: boolean };
type Record = { id: string; measured_at: string; value: string; unit: string; result: string; correction: string };
type Plan = { id: string; plan_id: string; version: number; data: Settings; overdue: boolean; due_at: string; last_record: Record | null; unresolved_deviations: Record[] };
type Pending = { path: string; body: { request_key: string; [key: string]: unknown } };
const principal = () => { const user = auth.getUser(); return JSON.stringify([user?.tenant_id, user?.sub]); };
const allowedPath = /^\/hygiene\/plans(?:\/[0-9a-f-]+\/checks)?$/;

export function HygienePanel({ venue }: { venue: Venue }) { return <HygieneView key={venue.id} venue={venue} />; }

function HygieneView({ venue }: { venue: Venue }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  const [checking, setChecking] = useState<{ plan: Plan; corrects?: Record } | null>(null);
  const mutation = useVenueMutation(venue.id, "flintplate:hygiene-pending:v1:", allowedPath);
  const { pending, busy, ready } = mutation;
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const manager = venue.role === "manager";
  const time = (value: string) => new Intl.DateTimeFormat("de-DE", { timeZone: venue.timezone, dateStyle: "short", timeStyle: "short" }).format(new Date(value));

  const load = useCallback(async () => {
    const scope = principal();
    const [nextPlans, nextMembers] = await Promise.all([
      venueApi<Plan[]>(venue.id, "/hygiene/plans"), venueApi<Member[]>(venue.id, "/members"),
    ]);
    if (scope === principal()) { setPlans(nextPlans); setMembers(nextMembers); }
  }, [venue.id]);

  useEffect(() => {
    let active = true;
    void load().catch(e => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [load]);

  async function saved() {
    setEditing(null); setChecking(null); setNotice("Kontrollnachweis gespeichert.");
    await load();
  }
  async function execute(command: Pending) {
    setError(""); setNotice("");
    if (await mutation.send(command.path, command.body, "Hygienekontrolle oder Plan speichern")) {
      await saved().catch(e => setError(message(e)));
    }
  }
  async function retry() {
    if (await mutation.retry()) await saved().catch(e => setError(message(e)));
  }
  const locked = busy || !ready || mutation.blocked || !!pending;
  function submitPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (locked || !editing) return;
    const form = new FormData(event.currentTarget);
    const data = { name: String(form.get("name")), location: String(form.get("location")), instructions: String(form.get("instructions")), minimum: String(form.get("minimum")), maximum: String(form.get("maximum")), unit: String(form.get("unit")), interval_minutes: Number(form.get("interval_minutes")), responsible_user_id: String(form.get("responsible_user_id")), active: form.get("active") === "on" };
    void execute({ path: "/hygiene/plans", body: { request_key: newRequestId(), data, ...(editing === "new" ? {} : { plan_id: editing.plan_id, expected_version: editing.version }) } });
  }
  function submitCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (locked || !checking) return;
    const form = new FormData(event.currentTarget);
    void execute({ path: `/hygiene/plans/${checking.plan.plan_id}/checks`, body: { request_key: newRequestId(), version: checking.plan.version, value: String(form.get("value")), correction: String(form.get("correction") ?? ""), corrects_id: checking.corrects?.id ?? null } });
  }
  async function download() {
    try {
      const end = new Date(), start = new Date(end.getTime() - 30 * 86400000);
      await load(); // Uses the shared session refresh before downloading a file.
      const base = process.env.NEXT_PUBLIC_API_URL ?? "/api";
      const response = await fetch(`${base}/gastro/venues/${venue.id}/hygiene/export.csv?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`, { headers: { Authorization: `Bearer ${auth.getAccess()}` }, cache: "no-store" });
      if (!response.ok) throw new Error("Kontrollnachweise konnten nicht geladen werden. Bitte Zeitraum und Sitzung prüfen.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = `flintplate-kontrollnachweise-${end.toISOString().slice(0, 10)}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(message(e)); }
  }
  const settings = editing && editing !== "new" ? editing.data : null;
  return <section className="fp-hygiene" aria-label="Hygieneplan">
    <div className="fp-section-head fp-hygiene-head"><div><h2>Kontrollen im Blick</h2><p>Fällige Aufgaben und offene Abweichungen nach eurem betrieblichen Hygienekonzept.</p></div><div className="fp-inline"><button className="fp-button ghost" disabled={busy} onClick={() => void load().catch(e => setError(message(e)))} aria-label="Kontrollplan aktualisieren"><RefreshCw size={18} /></button>{manager && <><button className="fp-button ghost" onClick={() => void download()}><Download size={16} /> CSV-Nachweise · 30 Tage</button><button className="fp-button" disabled={locked} onClick={() => setEditing("new")}><Plus size={16} /> Kontrollplan</button></>}</div></div>
    {(error || mutation.error) && <div className="fp-notice error" role="alert">{error || mutation.error}</div>}{notice && <div className="fp-notice" role="status">{notice}</div>}
    {pending && <div className="fp-notice"><p>Die Rückmeldung steht noch aus. Der Vorgang bleibt mit derselben ID gespeichert.</p><button className="fp-button" disabled={busy} onClick={() => void retry()}>Vorgang erneut prüfen</button></div>}
    {ready && !plans.length && <Empty title="Euer Hygienekonzept als täglicher Begleiter">Lege Kontrollaufgaben mit Grenzwerten, Intervall und verantwortlicher Person an.</Empty>}
    <div className="fp-card-grid">{(mutation.blocked ? [] : plans).map(plan => <article className="fp-panel" key={plan.plan_id}>
      <div className="fp-section-head"><h3>{plan.data.name}</h3><Tag tone={!plan.data.active ? "neutral" : plan.overdue ? "amber" : "green"}>{!plan.data.active ? "Pausiert" : plan.overdue ? "Fällig" : "Erledigt"}</Tag></div>
      <p>{plan.data.location} · {members.find(member => member.user_id === plan.data.responsible_user_id)?.full_name ?? "Verantwortliches Teammitglied"}</p><p>{plan.data.instructions}</p>
      <p className="fp-muted">{stockQuantity(plan.data.minimum)}–{stockQuantity(plan.data.maximum)} {plan.data.unit} · alle {plan.data.interval_minutes} Minuten · Version {plan.version}</p>
      <p>{plan.last_record ? `Letzte Kontrolle ${time(plan.last_record.measured_at)} · ${stockQuantity(plan.last_record.value)} ${plan.last_record.unit}` : "Für diese Planversion steht die erste Kontrolle aus."}</p>
      {plan.data.active && <p>Nächste Kontrolle: {time(plan.due_at)}</p>}
      {plan.unresolved_deviations.map(record => <div className="fp-notice error" key={record.id}><div><strong>Offene Abweichung: {stockQuantity(record.value)} {record.unit}</strong><p>{time(record.measured_at)} · {record.correction}</p><button className="fp-button ghost" disabled={locked || !plan.data.active} onClick={() => setChecking({ plan, corrects: record })}>Nachkontrolle erfassen</button></div></div>)}
      <div className="fp-inline"><button className="fp-button" disabled={locked || !plan.data.active} onClick={() => setChecking({ plan })}><ClipboardCheck size={16} /> Kontrolle erfassen</button>{manager && <button className="fp-button ghost" disabled={locked} onClick={() => setEditing(plan)}>Plan anpassen</button>}</div>
    </article>)}</div>
    {editing && <Modal title={editing === "new" ? "Kontrollplan anlegen" : "Kontrollplan versionieren"} onClose={() => setEditing(null)}>{(error || mutation.error) && <div className="fp-notice error" role="alert">{error || mutation.error}</div>}{pending && <div className="fp-panel"><p>Die Bestätigung steht aus; die gesicherten Angaben bleiben unverändert.</p><button className="fp-button" disabled={busy || mutation.blocked} onClick={() => void retry()}>Vorgang erneut prüfen</button></div>}<form onSubmit={submitPlan}><fieldset className="fp-fieldset" disabled={locked}>
      <Field label="Kontrollaufgabe"><input name="name" required minLength={2} maxLength={120} defaultValue={settings?.name} /></Field><Field label="Ort oder Gerät"><input name="location" required minLength={2} maxLength={120} defaultValue={settings?.location} /></Field>
      <Field label="Prüfanweisung"><textarea name="instructions" required minLength={5} maxLength={1000} defaultValue={settings?.instructions} /></Field>
      <div className="fp-two"><Field label="Untergrenze"><input name="minimum" type="number" step="0.001" required defaultValue={settings?.minimum ?? "0"} /></Field><Field label="Obergrenze"><input name="maximum" type="number" step="0.001" required defaultValue={settings?.maximum ?? "1"} /></Field></div>
      <Field label="Einheit"><input name="unit" required maxLength={20} defaultValue={settings?.unit ?? "Prüfwert"} /></Field><Field label="Intervall in Minuten"><input name="interval_minutes" type="number" min={15} max={44640} required defaultValue={settings?.interval_minutes ?? 1440} /></Field>
      <Field label="Verantwortlich"><select name="responsible_user_id" required defaultValue={settings?.responsible_user_id ?? ""}><option value="">Teammitglied wählen</option>{members.filter(member => member.active).map(member => <option value={member.user_id} key={member.id}>{member.full_name}</option>)}</select></Field>
      <label className="fp-check"><input name="active" type="checkbox" defaultChecked={settings?.active ?? true} /> Kontrollplan aktiv</label><p className="fp-muted">Grenzwerte folgen eurem betrieblichen Konzept. Eine neue Version benötigt eine neue Kontrolle; bisherige Nachweise bleiben erhalten.</p><button className="fp-button" disabled={locked}>Plan speichern</button>
    </fieldset></form></Modal>}
    {checking && <Modal title={checking.corrects ? "Nachkontrolle erfassen" : checking.plan.data.name} onClose={() => setChecking(null)}>{(error || mutation.error) && <div className="fp-notice error" role="alert">{error || mutation.error}</div>}{pending && <div className="fp-panel"><p>Die Bestätigung steht aus; die gesicherten Angaben bleiben unverändert.</p><button className="fp-button" disabled={busy || mutation.blocked} onClick={() => void retry()}>Vorgang erneut prüfen</button></div>}<form onSubmit={submitCheck}><fieldset className="fp-fieldset" disabled={locked}>
      <p>{checking.plan.data.location} · {checking.plan.data.instructions}</p><p>Freigegebener Bereich: {stockQuantity(checking.plan.data.minimum)}–{stockQuantity(checking.plan.data.maximum)} {checking.plan.data.unit}</p>
      {checking.corrects && <div className="fp-notice">Nachkontrolle zur Abweichung vom {time(checking.corrects.measured_at)}.</div>}
      <Field label={`Messwert (${checking.plan.data.unit})`}><input name="value" type="number" step="0.001" min={-100000} max={100000} required autoFocus /></Field><Field label="Sofortmaßnahme bei Abweichung"><textarea name="correction" maxLength={500} placeholder="Was wurde konkret getan?" /></Field><button className="fp-button" disabled={locked}>Kontrolle speichern</button>
    </fieldset></form></Modal>}
  </section>;
}
