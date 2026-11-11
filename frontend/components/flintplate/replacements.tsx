"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BellRing, RefreshCw, ShieldCheck } from "lucide-react";
import { day, time, money, message, venueApi, toISO, type Member, type Shift, type Venue } from "@/lib/flintplate";
import { Empty, Field, Modal, Tag } from "./shared";

const stations = { service: "Service", kitchen: "Küche", bar: "Bar", activities: "Aktivitäten" };
const states: Record<string, string> = { open: "Suche läuft", filled: "Vertretung gefunden", unfilled: "Ohne Zusage beendet", expired: "Abgelaufen", cancelled: "Zurückgezogen" };
interface Skills { user_id: string; stations: string[]; competence: number; emergency_opt_in: boolean }
interface Search { id: string; shift_id: string; mode: string; reason: string; status: string; version: number }
interface Candidate { worker_id: string; name: string; eligible: boolean; reasons: string[]; competence: number; planned_minutes: number; weekly_target_minutes: number | null; prior_requests: number; estimated_base_cents: number | null; score: number }
interface Proposal { request_key: string; shift_id: string; mode: string; reason: string; timeout_minutes: number; competence_weight: number; fairness_weight: number; capacity_weight: number }
interface Window { id: string; starts_at: string; ends_at: string }
interface Offer extends Window { station: string; expires_at: string; break_minutes: number; venue_name: string }

export function ReplacementManagement({ venue, members, shifts }: { venue: Venue; members: Member[]; shifts: Shift[] }) {
  const [searches, setSearches] = useState<Search[]>([]);
  const [skills, setSkills] = useState<Skills[]>([]);
  const [show, setShow] = useState(false);
  const [edit, setEdit] = useState<Skills | null>(null);
  const [preview, setPreview] = useState<{ proposal: Proposal; rows: Candidate[] } | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    const [requests, qualifications] = await Promise.all([
      venueApi<Search[]>(venue.id, "/emergencies"), venueApi<Skills[]>(venue.id, "/staff-skills"),
    ]);
    setSearches(requests); setSkills(qualifications);
  }, [venue.id]);
  useEffect(() => {
    void load().catch(e => setError(message(e)));
    const timer = setInterval(() => void load().catch(e => setError(message(e))), 20000);
    return () => clearInterval(timer);
  }, [load]);
  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); await load(); setNotice(success); return true; }
    catch (e) { setError(message(e)); return false; }
    finally { setBusy(false); }
  }
  async function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const proposal: Proposal = { request_key: newRequestId(), shift_id: String(form.get("shift")), mode: String(form.get("mode")), reason: String(form.get("reason")), timeout_minutes: Number(form.get("timeout")), competence_weight: Number(form.get("competence")), fairness_weight: Number(form.get("fairness")), capacity_weight: Number(form.get("capacity")) };
    await act(async () => {
      const rows = await venueApi<Candidate[]>(venue.id, "/emergency-preview", "POST", proposal);
      setPreview({ proposal, rows });
    }, "Eignung und Reihenfolge geprüft. Anfragen starten erst nach deiner Freigabe.");
  }
  const available = shifts.filter(s => s.status === "published" && new Date(s.starts_at).getTime() > Date.now() && !searches.some(r => r.shift_id === s.id && r.status === "open"));
  return <section className="fp-panel">
    <div className="fp-section-head"><div><h2>Jemand fällt aus?</h2><p>Geeignete Vertretung finden. Mit freiwilliger Bereitschaft und einer nachvollziehbaren Reihenfolge.</p></div><button className="fp-button primary" onClick={() => { setShow(true); setPreview(null); setUncertain(false); }}><BellRing size={18} /> Vertretung suchen</button></div>
    {error && <p className="fp-notice error" role="alert">{error}</p>}{notice && !show && <p className="fp-notice" role="status">{notice}</p>}
    <p className="fp-muted">Anfragen erscheinen in der Team-App. Externe Push-, SMS- und Telefonbenachrichtigungen sind noch nicht angebunden.</p>
    {searches.map(r => <div className="fp-list-row" key={r.id}><BellRing size={20} /><div><strong>{shifts.find(s => s.id === r.shift_id)?.station_label ?? shifts.find(s => s.id === r.shift_id)?.station ?? "Dienstvertretung"}</strong><small>{r.reason} · {r.mode === "broadcast" ? "Alle geeigneten Personen" : "Nacheinander"}</small></div><Tag tone={r.status === "filled" ? "green" : "neutral"}>{states[r.status]}</Tag>{r.status === "open" && <button className="fp-text-button" disabled={busy} onClick={() => void act(() => venueApi(venue.id, `/emergencies/${r.id}/cancel`, "POST", { version: r.version }), "Suche zurückgezogen.")}>Zurückziehen</button>}</div>)}
    <details className="fp-qualifications"><summary>Qualifikationen & Bereitschaft im Team</summary>{members.filter(m => m.active && m.role !== "manager").map(m => {
      const skill = skills.find(s => s.user_id === m.user_id);
      return <div className="fp-list-row" key={m.id}><ShieldCheck size={20} /><div><strong>{m.full_name}</strong><small>{skill?.stations.map(s => stations[s as keyof typeof stations]).join(", ") || "Noch keine Station dokumentiert"} · Erfahrung {skill?.competence ?? 1}/5</small><small>{skill?.emergency_opt_in ? "Freiwillige Anfragen aktiviert" : "Keine Freigabe für Anfragen"}</small></div><button className="fp-button" onClick={() => setEdit(skill ?? { user_id: m.user_id, stations: [], competence: 1, emergency_opt_in: false })}>Qualifikation bearbeiten</button></div>;
    })}</details>
    {show && <Modal title="Vertretung suchen" onClose={() => { if (!busy) setShow(false); }}>
      {!available.length ? <Empty title="Kein offener Dienst auswählbar">Veröffentliche einen zukünftigen Dienst. Für einen Dienst kann jeweils eine Suche laufen.</Empty> : <form onSubmit={compare} onChange={() => setPreview(null)}>
        <fieldset disabled={busy || uncertain} className="fp-fieldset">
          <Field label="Ausgefallener Dienst"><select name="shift" required>{available.map(s => <option key={s.id} value={s.id}>{day(s.starts_at, venue.timezone)} {time(s.starts_at, venue.timezone)} · {s.station_label??s.station} · {members.find(m => m.user_id === s.worker_id)?.full_name}</option>)}</select></Field>
          <Field label="Grund der Suche (nur Leitung)"><input name="reason" required minLength={3} maxLength={500} placeholder="Kurzfristiger Personalausfall" /></Field>
          <div className="fp-two"><Field label="Anfragemodus"><select name="mode"><option value="sequential">Nacheinander nach Rangfolge</option><option value="broadcast">Alle geeigneten Personen gleichzeitig</option></select></Field><Field label="Antwortfrist pro Anfrage (Minuten)"><input name="timeout" type="number" min={1} max={60} defaultValue={10} required /></Field></div>
          <details><summary>Rangfolge gewichten</summary><p>Eignung, Verfügbarkeit und Ruhezeiten gelten vor jeder Gewichtung.</p><div className="fp-two">{[["competence", "Kompetenz", 50], ["fairness", "Faire Verteilung", 30], ["capacity", "Offene Sollstunden", 20]].map(([key, label, value]) => <Field key={key} label={String(label)}><input name={String(key)} type="number" min={0} max={100} defaultValue={value} required /></Field>)}</div></details>
          <button className="fp-button wide" type="submit">Eignung & Reihenfolge prüfen</button>
        </fieldset>
      </form>}
      {error && <p className="fp-notice error" role="alert">{error}</p>}
      {preview && <><h3>Begründete Auswahl</h3>{preview.rows.length === 0 && <Empty title="Keine weiteren Mitarbeitenden">Ordne dem Betrieb weitere aktive Mitarbeitende zu.</Empty>}{preview.rows.map((c, i) => <div className="fp-candidate" key={c.worker_id}><div className="fp-section-head"><strong>{i + 1}. {c.name}</strong><Tag tone={c.eligible ? "green" : "neutral"}>{c.eligible ? `${c.score} Punkte` : "Nicht anfragen"}</Tag></div><p>Erfahrung {c.competence}/5 · {(c.planned_minutes / 60).toFixed(1)} geplante Stunden{c.weekly_target_minutes !== null ? ` / ${c.weekly_target_minutes / 60} Soll` : ""} · {c.prior_requests} Anfragen in 30 Tagen</p>{c.estimated_base_cents !== null && <small>Grundlohn-Schätzung {money(c.estimated_base_cents)}; Zuschläge und Arbeitgeberanteile fehlen.</small>}{c.reasons.length > 0 && <ul>{c.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}</div>)}
        <button className="fp-button primary wide" disabled={busy || !preview.rows.some(c => c.eligible)} onClick={() => void act(async () => { setUncertain(true); await venueApi(venue.id, "/emergencies", "POST", preview.proposal); setUncertain(false); setShow(false); }, "Vertretungssuche gestartet. Geeignete Mitarbeitende sehen die Anfrage in ihrer Team-App.")}>{uncertain ? "Status desselben Vorgangs erneut prüfen" : "Verbindliche Anfragen jetzt starten"}</button>
      </>}
    </Modal>}
    {edit && <Modal title="Stationsqualifikation dokumentieren" onClose={() => setEdit(null)}><form onSubmit={async e => { e.preventDefault(); const f = new FormData(e.currentTarget); if (await act(() => venueApi(venue.id, `/staff-skills/${edit.user_id}`, "PUT", { stations: f.getAll("stations"), competence: Number(f.get("competence")) }), "Qualifikation gespeichert.")) setEdit(null); }}>
      <p>{members.find(m => m.user_id === edit.user_id)?.full_name}</p>{Object.entries(stations).map(([key, name]) => <label className="fp-check" key={key}><input name="stations" type="checkbox" value={key} defaultChecked={edit.stations.includes(key)} /> {name}</label>)}
      <Field label="Dokumentierte Erfahrung (1 bis 5)"><input name="competence" type="number" min={1} max={5} defaultValue={edit.competence} required /></Field><p>Die Bereitschaft zu Anfragen gibt die Person selbst in der Team-App frei.</p><button className="fp-button primary wide" disabled={busy}>Speichern</button>
    </form></Modal>}
  </section>;
}

export function ReplacementInbox({ venue, onChange }: { venue: Venue; onChange: () => Promise<void> }) {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [windows, setWindows] = useState<Window[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    const [requests, availability, optIn] = await Promise.all([venueApi<Offer[]>(venue.id, "/my-replacement-offers"), venueApi<Window[]>(venue.id, "/my-availability"), venueApi<{ enabled: boolean }>(venue.id, "/my-emergency-opt-in")]);
    setOffers(requests); setWindows(availability); setEnabled(optIn.enabled); setLoaded(true);
  }, [venue.id]);
  useEffect(() => { void load().catch(e => setError(message(e))); const timer = setInterval(() => void load().catch(e => setError(message(e))), 15000); return () => clearInterval(timer); }, [load]);
  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); await load(); await onChange(); setNotice(success); }
    catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return <section className="fp-panel"><div className="fp-section-head"><div><h2>Füreinander einspringen</h2><p>{venue.name}</p></div><button className="fp-icon" aria-label="Vertretungsanfragen aktualisieren" disabled={busy} onClick={() => void act(load, "Anfragen aktualisiert.")}><RefreshCw size={19} /></button></div>
    {error && <p role="alert" className="fp-notice error">{error}</p>}{notice && <p role="status" className="fp-notice">{notice}</p>}
    <label className="fp-check"><input type="checkbox" checked={enabled} disabled={busy || !loaded} onChange={e => { const checked = e.target.checked; void act(() => venueApi(venue.id, "/my-emergency-opt-in", "PUT", { enabled: checked }), checked ? "Freiwillige Anfragen aktiviert." : "Keine neuen Vertretungsanfragen freigegeben."); }} /> Ich möchte freiwillig Vertretungsanfragen erhalten.</label>
    <p className="fp-muted">Du entscheidest über deine Zeitfenster und jede Zusage. Anfragen werden hier bei geöffneter App aktualisiert; Push und SMS folgen separat.</p>
    {offers.map(o => <article className="fp-candidate" key={o.id}><Tag tone="green">Vertretung angefragt</Tag><h3>{o.station}</h3><p>{day(o.starts_at, venue.timezone)} · {time(o.starts_at, venue.timezone)}–{time(o.ends_at, venue.timezone)} · {o.break_minutes} Min. Pause</p><p>Antwort bis {time(o.expires_at, venue.timezone)} Uhr. Mit deiner Zusage übernimmst du den Dienst verbindlich.</p><div className="fp-two"><button className="fp-button primary" disabled={busy} onClick={() => void act(() => venueApi(venue.id, `/my-replacement-offers/${o.id}`, "POST", { accept: true }), "Dienst übernommen. Dein Dienstplan ist aktualisiert.")}>Dienst übernehmen</button><button className="fp-button" disabled={busy} onClick={() => void act(() => venueApi(venue.id, `/my-replacement-offers/${o.id}`, "POST", { accept: false }), "Absage gespeichert.")}>Diesmal nicht</button></div></article>)}
    {loaded && !offers.length && <p>Aktuell liegt keine offene Anfrage für dich vor.</p>}
    <h3>Deine angebotenen Zeitfenster</h3>{windows.map(w => <div className="fp-list-row" key={w.id}><div><strong>{day(w.starts_at, venue.timezone)} {time(w.starts_at, venue.timezone)} – {day(w.ends_at, venue.timezone)} {time(w.ends_at, venue.timezone)}</strong></div><button className="fp-text-button" disabled={busy} onClick={() => void act(() => venueApi(venue.id, `/my-availability/${w.id}`, "DELETE"), "Zeitfenster zurückgezogen.")}>Zurückziehen</button></div>)}
    <form onSubmit={async e => { e.preventDefault(); const form = e.currentTarget; const f = new FormData(form); await act(() => venueApi(venue.id, "/my-availability", "POST", { starts_at: toISO(f.get("start")), ends_at: toISO(f.get("end")) }), "Zeitfenster angeboten."); }}><div className="fp-two"><Field label="Verfügbar ab (Gerätezeit)"><input name="start" type="datetime-local" required /></Field><Field label="Verfügbar bis (Gerätezeit)"><input name="end" type="datetime-local" required /></Field></div><button className="fp-button wide" disabled={busy}>Zeitfenster anbieten</button></form>
  </section>;
}
