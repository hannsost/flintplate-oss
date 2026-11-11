"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CalendarPlus, Check, Clock3, ListPlus, Plus, RefreshCw, Users } from "lucide-react";
import { day, message, str, time, toISO, venueApi, type Reservation, type Resource, type Venue } from "@/lib/flintplate";
import { useVenueMutation } from "@/lib/flintplate-pending";
import type { Action, Data } from "./operations";
import { Empty, Field, Loading, Modal, Tag, since, useLive, useNow } from "./shared";
import { SeatingAssistant } from "./seating";

type Group = Reservation & { table_ids: string[]; source: string; note: string; checked_in_at: string | null; closed_at: string | null };
type Waiting = { id: string; guest_name: string; guests: number; note: string; status: string; version: number; reservation_id: string | null; created_at: string; closed_at: string | null };
type Board = { reservations: Group[]; waitlist: Waiting[] };
type Dialog = { kind: "reservation" | "walk_in" | "waitlist" | "seat" | "extend" | "state"; group?: Group; waiting?: Waiting; status?: "completed" | "cancelled" | "no_show" };
const PATHS = /^\/(reservation-groups(?:\/[a-f0-9-]+\/(?:state|extend))?|waitlist(?:\/[a-f0-9-]+\/(?:seat|state))?)$/;
const stateLabels: Record<string, string> = { confirmed: "Erwartet", seated: "Anwesend", completed: "Beendet", cancelled: "Storniert", no_show: "Nicht erschienen" };
const localInput = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
const connected = (left: Resource, right: Resource) => left.combinable_with.includes(right.id) || right.combinable_with.includes(left.id);

export function ReservationsPanel({ venue, data, act, onVisit }: { venue: Venue; data: Data; act: Action; onVisit?: (reservation: Reservation) => void }) {
  const now = useNow(15000);
  const [date, setDate] = useState(() => localInput(new Date()).slice(0, 10));
  const [board, setBoard] = useState<Board | null>(null);
  const [view, setView] = useState<"live" | "waiting" | "closed">("live");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [assistant, setAssistant] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [primary, setPrimary] = useState("");
  const [additional, setAdditional] = useState<string[]>([]);
  const [guests, setGuests] = useState(2);
  const [duration, setDuration] = useState("90");
  const [end, setEnd] = useState("");
  const reloadVersion = useRef(0);
  const mutation = useVenueMutation(venue.id, "flintplate:reservation-pending:v1:", PATHS);
  const locked = mutation.busy || refreshing || !!mutation.pending || mutation.blocked || !mutation.ready;
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const load = useCallback(async () => {
    const version = ++reloadVersion.current;
    const start = new Date(`${date}T00:00:00`);
    const finish = new Date(start); finish.setDate(finish.getDate() + 1);
    const next = await venueApi<Board>(venue.id, `/reservations/board?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(finish.toISOString())}`);
    if (version === reloadVersion.current) setBoard(next);
  }, [date, venue.id]);
  useEffect(() => { void load().catch(cause => setError(message(cause))); }, [load]);
  useLive(load);

  async function complete(ok: boolean) {
    if (!ok) return;
    setDialog(null); setNotice(""); setRefreshing(true);
    try { const updated = await act(load, "Reservierungen aktualisiert."); setNotice(updated ? "Gespeichert. Belegung und Warteliste sind aktualisiert." : "Gespeichert. Die Ansicht konnte noch nicht aktualisiert werden."); }
    finally { setRefreshing(false); }
  }
  async function send(path: string, payload: Record<string, unknown>, label: string) {
    if (locked) return;
    setError(""); setNotice("");
    await complete(await mutation.send(path, payload, label));
  }
  function open(next: Dialog) {
    if (locked) return;
    setError(""); mutation.clearError(); setDialog(next); setAdditional([]);
    setGuests(next.waiting?.guests ?? next.group?.guests ?? 2);
    setPrimary(next.group?.table_id ?? ""); setDuration("90");
    setEnd(localInput(new Date(next.group ? Math.max(new Date(next.group.ends_at).getTime(), Date.now()) + 30 * 60000 : Date.now() + 90 * 60000)));
  }
  const ids = primary ? [primary, ...additional] : [];
  const selected = data.resources.filter(resource => ids.includes(resource.id));
  const main = data.resources.find(resource => resource.id === primary);
  const tablesOnly = dialog?.kind === "walk_in" || dialog?.kind === "seat";
  const occupied = new Set(board?.reservations.filter(group => group.status === "seated").flatMap(group => group.table_ids) ?? []);
  const choices = data.resources.filter(resource => !tablesOnly || resource.kind === "table");
  const neighbours = main?.kind === "table" ? data.resources.filter(resource => resource.kind === "table" && resource.id !== main.id && resource.room_id === main.room_id && resource.area === main.area) : [];
  const reached = new Set(primary ? [primary] : []);
  for (let pass = 0; pass < selected.length; pass++) for (const resource of selected) if (selected.some(other => reached.has(other.id) && connected(other, resource))) reached.add(resource.id);
  const coherent = ids.length > 0 && ids.every(id => reached.has(id));
  const seats = selected.reduce((sum, resource) => sum + resource.seats, 0);
  const needsTable = !!dialog && ["reservation", "walk_in", "seat"].includes(dialog.kind);
  const selectionValid = !needsTable || (coherent && seats >= guests && ids.length <= 8);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.pending) { await complete(await mutation.retry()); return; }
    if (!dialog || !selectionValid || locked) return;
    const form = new FormData(event.currentTarget);
    if (dialog.kind === "waitlist") await send("/waitlist", { guest_name: str(form, "name"), guests, note: str(form, "note") }, `Warteliste · ${str(form, "name")}`);
    if (dialog.kind === "reservation" || dialog.kind === "walk_in") await send("/reservation-groups", {
      table_ids: ids, guest_name: str(form, "name"), guests, note: str(form, "note"), source: dialog.kind,
      starts_at: dialog.kind === "walk_in" ? new Date().toISOString() : toISO(form.get("start")),
      ends_at: dialog.kind === "walk_in" ? new Date(Date.now() + Number(duration) * 60000).toISOString() : toISO(form.get("end")),
    }, `${dialog.kind === "walk_in" ? "Spontane Gäste" : "Reservierung"} · ${str(form, "name")}`);
    if (dialog.kind === "seat" && dialog.waiting) await send(`/waitlist/${dialog.waiting.id}/seat`, { version: dialog.waiting.version, table_ids: ids, ends_at: new Date(Date.now() + Number(duration) * 60000).toISOString() }, `Warteliste platzieren · ${dialog.waiting.guest_name}`);
    if (dialog.kind === "extend" && dialog.group) await send(`/reservation-groups/${dialog.group.id}/extend`, { version: dialog.group.version, ends_at: toISO(form.get("end")), reason: str(form, "reason") }, `Verlängerung · ${dialog.group.guest_name}`);
    if (dialog.kind === "state" && dialog.group) await send(`/reservation-groups/${dialog.group.id}/state`, { version: dialog.group.version, status: dialog.status }, `${stateLabels[dialog.status ?? "cancelled"]} · ${dialog.group.guest_name}`);
    if (dialog.kind === "state" && dialog.waiting) await send(`/waitlist/${dialog.waiting.id}/state`, { version: dialog.waiting.version, status: "cancelled" }, `Warteliste verlassen · ${dialog.waiting.guest_name}`);
  }
  const tableNames = (group: Group) => group.table_ids.map(id => data.resources.find(resource => resource.id === id)?.name ?? "Unbekannter Tisch").join(" + ");
  const live = board?.reservations.filter(group => ["confirmed", "seated"].includes(group.status)).sort((left, right) => Number(right.status === "seated") - Number(left.status === "seated") || left.starts_at.localeCompare(right.starts_at)) ?? [];
  const closed = board?.reservations.filter(group => !["confirmed", "seated"].includes(group.status)) ?? [];
  const rows = view === "closed" ? closed : live;
  const titles = { reservation: "Reservierung eintragen", walk_in: "Spontane Gäste platzieren", waitlist: "Auf die Warteliste", seat: "Gästen einen Platz geben", extend: "Aufenthalt verlängern", state: dialog?.waiting ? "Warteliste verlassen" : dialog?.status === "no_show" ? "Nicht erschienen" : dialog?.status === "completed" ? "Aufenthalt beenden" : "Reservierung stornieren" };

  return <>
    <section className="fp-panel"><div className="fp-section-head"><div><h2>Ein Platz für deine Gäste.</h2><p>Ankünfte, spontane Gäste und gemeinsame Tischreservierungen.</p></div><button className="fp-icon" aria-label="Reservierungen aktualisieren" onClick={() => void load().catch(cause => setError(message(cause)))}><RefreshCw size={18} /></button></div>
      <div className="fp-inline wrap"><button className="fp-button primary" disabled={locked} onClick={() => open({ kind: "walk_in" })}><Users size={18} /> Spontane Gäste</button><button className="fp-button" disabled={locked} onClick={() => open({ kind: "reservation" })}><CalendarPlus size={18} /> Reservierung</button><button className="fp-button" disabled={locked} onClick={() => open({ kind: "waitlist" })}><ListPlus size={18} /> Warteliste</button><button className="fp-text-button" disabled={locked} onClick={() => setAssistant(true)}>Platz vorschlagen</button></div>
      <div className="fp-booking-toolbar"><Field label={`Tag (${zone})`}><input type="date" value={date} required onChange={event => { if (event.target.value) setDate(event.target.value); }} /></Field><button className="fp-button" onClick={() => setDate(localInput(new Date()).slice(0, 10))}>Heute</button><span>Anwesende Gruppen bleiben unabhängig vom gewählten Tag sichtbar.</span></div>
      <div className="fp-inline wrap" role="group" aria-label="Reservierungsansicht">{([['live', `Im Betrieb · ${live.length}`], ['waiting', `Warteliste · ${board?.waitlist.length ?? 0}`], ['closed', 'Erledigt']] as const).map(([value, label]) => <button key={value} className={`fp-button ${view === value ? "primary" : ""}`} aria-pressed={view === value} onClick={() => setView(value)}>{label}</button>)}</div>
    </section>
    {(error || mutation.error) && <p className="fp-notice error" role="alert">{error || mutation.error}</p>}{notice && <p className="fp-notice" role="status">{notice}</p>}
    {mutation.pending && !dialog && <section className="fp-panel"><strong>{mutation.pending.label}</strong><p>Die Bestätigung steht noch aus. Die ursprünglichen Angaben sind auf diesem Gerät gesichert.</p><button className="fp-button primary" disabled={mutation.busy || mutation.blocked} onClick={() => void mutation.retry().then(complete)}>Reservierungsvorgang erneut prüfen</button></section>}
    {!board ? <Loading /> : view === "waiting" ? <section className="fp-stack">{board.waitlist.map(waiting => <article className="fp-panel" key={waiting.id}><div className="fp-section-head"><div><h3>{waiting.guest_name}</h3><p>{waiting.guests} Personen · {since(waiting.created_at, now)}</p></div><Tag tone="amber">Wartet</Tag></div>{waiting.note && <p>{waiting.note}</p>}<div className="fp-inline wrap"><button className="fp-button primary" disabled={locked} onClick={() => open({ kind: "seat", waiting })}>Platz zuweisen</button><button className="fp-text-button" disabled={locked} onClick={() => open({ kind: "state", waiting })}>Warteliste verlassen</button></div></article>)}{!board.waitlist.length && <section className="fp-panel"><Empty title="Gerade wartet niemand">Neue Gäste ohne freien Tisch können hier aufgenommen werden.</Empty></section>}</section> : <section className="fp-card-grid">{rows.map(group => {
      const late = group.status === "confirmed" && now > new Date(group.starts_at).getTime();
      const overdue = group.status === "seated" && now > new Date(group.ends_at).getTime();
      return <article className="fp-panel fp-booking-card" key={group.id}><div className="fp-section-head"><div><h3>{group.guest_name}</h3><p>{group.guests} Personen · {tableNames(group)}</p></div><Tag tone={group.status === "seated" ? "green" : late ? "amber" : "neutral"}>{stateLabels[group.status] ?? group.status}</Tag></div><p><Clock3 size={15} /> {day(group.starts_at, venue.timezone)} · {time(group.starts_at, venue.timezone)}–{time(group.ends_at, venue.timezone)}</p>{group.table_ids.length > 1 && <small>{group.table_ids.length} verbundene Tische · ein gemeinsamer Vorgang</small>}{group.note && <p>{group.note}</p>}{(late || overdue) && <p className="fp-notice">{overdue ? "Geplante Aufenthaltszeit überschritten. Belegung bleibt bis zum Abschluss bestehen." : "Geplanter Beginn ist vorbei. Ankunft prüfen."}</p>}<div className="fp-inline wrap">{group.status === "confirmed" && <><button className="fp-button primary" disabled={locked} onClick={() => void send(`/reservation-groups/${group.id}/state`, { version: group.version, status: "seated" }, `Einchecken · ${group.guest_name}`)}><Check size={17} /> Einchecken</button><button className="fp-button" disabled={locked} onClick={() => open({ kind: "extend", group })}>Verlängern</button><button className="fp-button" disabled={locked} onClick={() => open({ kind: "state", group, status: "cancelled" })}>Stornieren</button>{late && <button className="fp-text-button" disabled={locked} onClick={() => open({ kind: "state", group, status: "no_show" })}>Nicht erschienen</button>}</>}{group.status === "seated" && onVisit && <button className="fp-button" disabled={locked} onClick={()=>onVisit(group)}>Gäste & Runden öffnen</button>}{group.status === "seated" && <><button className="fp-button" disabled={locked} onClick={() => open({ kind: "extend", group })}>Verlängern</button><button className="fp-button primary" disabled={locked} onClick={() => open({ kind: "state", group, status: "completed" })}>Aufenthalt beenden</button></>}</div></article>;
    })}{!rows.length && <section className="fp-panel"><Empty title={view === "closed" ? "Keine erledigten Vorgänge an diesem Tag" : "Platz für neue Pläne"}>Reservierungen und spontane Gäste erscheinen hier.</Empty></section>}</section>}
    {dialog && <Modal title={titles[dialog.kind]} onClose={() => { if (!mutation.busy) setDialog(null); }}><form onSubmit={submit}>
      {mutation.error && <p className="fp-notice error" role="alert">{mutation.error}</p>}{mutation.pending && <p className="fp-notice">Bestätigung ausstehend. Erneut prüfen verwendet dieselben Angaben, auch nach einem Neuladen.</p>}
      <fieldset disabled={locked} className="fp-fieldset">
        {["reservation", "walk_in", "waitlist"].includes(dialog.kind) && <><Field label="Gast / Gruppe"><input name="name" required maxLength={120} /></Field><Field label="Personen"><input name="guests" type="number" min={1} max={100} value={guests} onChange={event => setGuests(Number(event.target.value))} required /></Field></>}
        {dialog.waiting && <p><strong>{dialog.waiting.guest_name}</strong> · {dialog.waiting.guests} Personen</p>}
        {dialog.group && <p><strong>{dialog.group.guest_name}</strong> · {tableNames(dialog.group)}<br />{day(dialog.group.starts_at, venue.timezone)} · {time(dialog.group.starts_at, venue.timezone)}–{time(dialog.group.ends_at, venue.timezone)}</p>}
        {needsTable && <><Field label={tablesOnly ? "Tisch" : "Tisch oder Aktivität"}><select value={primary} onChange={event => { setPrimary(event.target.value); setAdditional([]); }} required><option value="">Bitte wählen</option>{choices.map(resource => <option key={resource.id} value={resource.id} disabled={tablesOnly && occupied.has(resource.id)}>{resource.name} · {resource.seats} Plätze{tablesOnly && occupied.has(resource.id) ? " · anwesende Gäste" : ""}</option>)}</select></Field>{main?.kind === "table" && neighbours.length > 0 && <details><summary><Plus size={15} /> Weitere Tische verbinden</summary><div className="fp-booking-tables">{neighbours.map(resource => <label className="fp-check" key={resource.id}><input type="checkbox" checked={additional.includes(resource.id)} disabled={(additional.length >= 7 && !additional.includes(resource.id)) || (tablesOnly && occupied.has(resource.id))} onChange={event => setAdditional(previous => event.target.checked ? [...previous, resource.id] : previous.filter(id => id !== resource.id))} /> {resource.name} · {resource.seats} Plätze</label>)}</div><small>Die gewählten Tische müssen durch konfigurierte Nachbarschaften verbunden sein.</small></details>}{primary && <p className={`fp-notice ${selectionValid ? "" : "error"}`}>{selected.map(resource => resource.name).join(" + ")} · {seats} Plätze für {guests} Gäste{!coherent ? " · Diese Auswahl ist nicht als verbundene Tischgruppe konfiguriert." : seats < guests ? " · Bitte mehr Plätze wählen." : ""}</p>}</>}
        {dialog.kind === "reservation" && <div className="fp-two"><Field label={`Beginn (${zone})`}><input name="start" type="datetime-local" defaultValue={`${date}T18:00`} required /></Field><Field label={`Ende (${zone})`}><input name="end" type="datetime-local" defaultValue={`${date}T19:30`} required /></Field></div>}
        {(dialog.kind === "walk_in" || dialog.kind === "seat") && <><p>Die Gäste werden jetzt eingecheckt.</p><Field label="Geplanter Aufenthalt in Minuten"><input name="duration" type="number" min={1} max={1440} value={duration} onChange={event => setDuration(event.target.value)} required /></Field><div className="fp-inline wrap">{[60, 90, 120].map(minutes => <button key={minutes} type="button" className="fp-button" aria-pressed={duration === String(minutes)} onClick={() => setDuration(String(minutes))}>{minutes} Min.</button>)}</div></>}
        {dialog.kind === "extend" && dialog.group && <><div className="fp-inline wrap">{[30, 60].map(minutes => <button type="button" className="fp-button" key={minutes} onClick={() => setEnd(localInput(new Date(new Date(dialog.group!.ends_at).getTime() + minutes * 60000)))}>+{minutes} Min.</button>)}</div><Field label={`Neues Ende (${zone})`}><input name="end" type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} required /></Field><Field label="Grund der Verlängerung"><input name="reason" minLength={3} maxLength={300} defaultValue="Aufenthalt verlängert" required /></Field><p>Die Verfügbarkeit aller verbundenen Tische wird gemeinsam geprüft.</p></>}
        {["reservation", "walk_in", "waitlist"].includes(dialog.kind) && <Field label="Notiz (optional)"><textarea name="note" maxLength={500} /></Field>}
        {dialog.kind === "state" && <p>{dialog.waiting ? "Die Gruppe wird aus der aktiven Warteliste entfernt." : dialog.status === "no_show" ? "Die Gäste sind nicht erschienen. Alle zugehörigen Tische werden für diese Reservierung freigegeben." : dialog.status === "completed" ? "Der Aufenthalt an allen verbundenen Tischen endet. Offene Bons bleiben in der Kasse sichtbar." : "Die Reservierung aller verbundenen Tische wird storniert."}</p>}
      </fieldset>
      <button className="fp-button primary wide" disabled={mutation.busy || refreshing || mutation.blocked || !mutation.ready || (!mutation.pending && !selectionValid)}>{mutation.busy ? "Wird gespeichert …" : mutation.pending ? "Vorgang erneut prüfen" : dialog.kind === "waitlist" ? "Auf Warteliste aufnehmen" : dialog.kind === "walk_in" || dialog.kind === "seat" ? "Jetzt platzieren" : dialog.kind === "extend" ? "Verlängerung bestätigen" : dialog.kind === "state" ? "Änderung bestätigen" : "Verbindlich reservieren"}</button>
    </form></Modal>}
    {assistant && <Modal title="Platz vorschlagen" onClose={() => setAssistant(false)}><SeatingAssistant venue={venue} resources={data.resources} onBooked={note => { setAssistant(false); setNotice(note); void act(load, note); }} /></Modal>}
  </>;
}
