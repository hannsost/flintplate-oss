"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Banknote, ChevronLeft, Plus, Settings2, Users } from "lucide-react";
import { auth } from "@/lib/auth";
import { usePendingRounds } from "@/lib/flintplate-round-pending";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { date, labels, message, money, str, time, venueApi, type Item, type Member, type Resource, type Reservation, type Venue } from "@/lib/flintplate";
import { guestTabLabel, serviceWorkflows, visitLabel, type AssignedUnit, type GuestTab, type ServiceCommand, type ServicePage, type ServiceRound, type ServiceSettings, type ServiceVisit } from "@/lib/flintplate-visits";
import { Empty, Field, Loading, Modal } from "./shared";
import { OrderComposer } from "./order-composer";
import { OrderCancellationButton } from "./order-cancellations";
import "./visits.css";

const PATHS = /^\/(?:service-settings|service-visits(?:\/[^/]+(?:\/(?:guest-tabs|end))?)?|guest-tabs\/[^/]+\/context)$/;
const identity = () => { const user = auth.getUser(); return user?.sub ? JSON.stringify([user.tenant_id, user.sub]) : null; };
const activeKey = (venueId: string) => `flintplate:service-context:v1:${encodeURIComponent(identity() ?? "")}:${venueId}`;
const initialSettings: ServiceSettings = { workflow: "table", guest_label_mode: "number", version: 0 };

export function VisitsPanel(props: { venue: Venue; items: Item[]; resources: Resource[]; members: Member[]; reservations?: Reservation[]; initialReservationId?: string; initialTable?: string; initialVisitId?: string; onChanged: () => Promise<unknown>; onCash: (visitId: string, guestTabId?: string) => void }) {
  return <VisitsView key={`${props.venue.id}:${props.initialTable ?? ""}:${props.initialVisitId ?? ""}:${props.initialReservationId ?? ""}`} {...props} />;
}

function VisitsView({ venue, items, resources, members, reservations = [], initialReservationId = "", initialTable = "", initialVisitId = "", onChanged, onCash }: Parameters<typeof VisitsPanel>[0]) {
  const [settings, setSettings] = useState(initialSettings);
  const [page, setPage] = useState<ServicePage<ServiceVisit>>({ items: [], next_before: null, has_more: false });
  const [visit, setVisit] = useState<ServiceVisit | null>(null);
  const selected = useRef(initialVisitId);
  const [guestId, setGuestId] = useState("");
  const [roundPending, setRoundPending] = useState<{ visitId: string; pending: boolean } | null>(null);
  const pendingRounds = usePendingRounds(venue.id);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [search, setSearch] = useState("");
  const [includeEnded, setIncludeEnded] = useState(false);
  const [creating, setCreating] = useState(!!initialReservationId);
  const [reservationId,setReservationId]=useState(initialReservationId);
  const [createTable,setCreateTable]=useState(initialTable);
  const [placeFilter,setPlaceFilter]=useState(initialTable);
  const [editing, setEditing] = useState<GuestTab | null>(null);
  const [ending, setEnding] = useState(false);
  const [config, setConfig] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const owner = useRef<string | null>(null);
  const live = useRef(false);
  const readGeneration = useRef(0);
  const keep = useCallback((next: ServiceVisit | null) => {
    if (!live.current || owner.current !== identity()) return;
    if (selected.current !== (next?.id ?? "")) setRoundPending(null);
    selected.current = next?.id ?? "";
    setVisit(next);
    setGuestId(current => next?.tabs.some(tab => tab.id === current) ? current : next?.tabs.find(tab => tab.kind === "guest")?.id ?? "");
    try { if (next) localStorage.setItem(activeKey(venue.id), next.id); else localStorage.removeItem(activeKey(venue.id)); }
    catch { /* Context is only a navigation preference. Order persistence has its own guard. */ }
  }, [venue.id]);
  const reload = useCallback(async (nextId = selected.current) => {
    const scope = identity(), generation = ++readGeneration.current;
    if (!scope || scope !== owner.current) return;
    setRefreshing(true);
    try {
      const [nextSettings, nextPage, nextVisit] = await Promise.all([
        venueApi<ServiceSettings>(venue.id, "/service-settings"),
        venueApi<ServicePage<ServiceVisit>>(venue.id, `/service-visits?active=${!includeEnded}&limit=50${initialTable ? `&table_id=${initialTable}` : ""}`),
        nextId ? venueApi<ServiceVisit>(venue.id, `/service-visits/${nextId}`) : Promise.resolve(null),
      ]);
      if (!live.current || scope !== identity() || generation !== readGeneration.current) return;
      setSettings(nextSettings); setPage(nextPage); keep(nextVisit); setLoaded(true); setError("");
    } finally { if (live.current && scope === identity() && generation === readGeneration.current) setRefreshing(false); }
  }, [venue.id, initialTable, includeEnded, keep]);
  const afterCommit = async (result: unknown) => {
    const value = result && typeof result === "object" ? result as Record<string, unknown> : {};
    const nextId = "tabs" in value && typeof value.id === "string" ? value.id : typeof value.visit_id === "string" ? value.visit_id : selected.current;
    await reload(nextId);
    if (owner.current !== identity() || !live.current) return;
    if (typeof value.visit_id === "string" && typeof value.id === "string") setGuestId(value.id);
    setCreating(false); setEditing(null); setEnding(false); setConfig(false);
    await onChanged();
  };
  const mutation = useVenueMutation(venue.id, "flintplate:visit-pending:v1:", PATHS, afterCommit);
  const mutationLocked = !loaded || refreshing || !mutation.ready || mutation.busy || mutation.blocked || !!mutation.pending;
  const onRoundBusyChange = useCallback((pending: boolean) => {
    if (live.current && owner.current === identity() && visit?.id && selected.current === visit.id) {
      setRoundPending({ visitId: visit.id, pending });
    }
  }, [visit?.id]);
  const locked = mutationLocked || (roundPending?.visitId === visit?.id && roundPending?.pending) || pendingRounds.length > 0;

  useEffect(() => {
    live.current = true; owner.current = identity();
    if (!initialVisitId && !initialTable) { try { selected.current = localStorage.getItem(activeKey(venue.id)) ?? ""; } catch { selected.current = ""; } }
    const changed = () => { if (owner.current !== identity()) { readGeneration.current++; setVisit(null); setRoundPending(null); setPage({ items: [], next_before: null, has_more: false }); setLoaded(false); setError("Bitte erneut persönlich anmelden."); } };
    window.addEventListener(AUTH_CHANGED_EVENT, changed); window.addEventListener("storage", changed);
    return () => { live.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", changed); };
  }, [venue.id, initialVisitId, initialTable]);
  useEffect(() => { void reload().catch(cause => { if (live.current && owner.current === identity()) setError(message(cause)); }); }, [reload]);
  async function select(id: string) { setNotice(""); try { await reload(id); } catch (cause) { setError(message(cause)); } }
  async function more() {
    if (!page.next_before || locked) return;
    const scope = identity(); setRefreshing(true);
    try {
      const next = await venueApi<ServicePage<ServiceVisit>>(venue.id, `/service-visits?active=${!includeEnded}&limit=50&before=${page.next_before}${initialTable ? `&table_id=${initialTable}` : ""}`);
      if (live.current && scope === identity()) setPage(current => ({ ...next, items: [...current.items, ...next.items.filter(item => !current.items.some(prior => prior.id === item.id))] }));
    } catch (cause) { if (scope === identity()) setError(message(cause)); }
    finally { if (scope === identity()) setRefreshing(false); }
  }
  async function addGuest() {
    if (!visit || locked || visit.ended_at) return;
    const table = visit.tabs.find(tab => tab.id === guestId)?.current_table_id ?? (initialTable || null);
    await mutation.send(`/service-visits/${visit.id}/guest-tabs`, { visit_version: visit.version, kind: "guest", label: "", current_table_id: table, seat_label: "", present: true }, "Gast hinzugefügt.");
  }
  const tabName = (tab: GuestTab) => guestTabLabel(tab, settings.guest_label_mode);
  const filtered = page.items.filter(value => (settings.workflow==="counter"||!placeFilter||value.tabs.some(tab=>tab.current_table_id===placeFilter))).filter(value => `${value.number} ${value.label} ${value.tabs.map(tab => `${tabName(tab)} ${tab.label} ${resources.find(row => row.id === tab.current_table_id)?.name ?? ""}`).join(" ")}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  return <div className="fp-visits" data-service-workflow={settings.workflow}>
    <section className="fp-panel fp-visit-head">
      <div className="fp-section-head"><div><h2>Gäste & Bestellrunden</h2><p>{serviceWorkflows[settings.workflow]} · Namen sind optional.</p></div><div className="fp-inline wrap"><button className="fp-button primary" disabled={locked} onClick={() => {setCreateTable(settings.workflow==="counter"?"":placeFilter||initialTable);setReservationId("");setCreating(true);}}><Plus size={17} /> Neuer Besuch</button>{venue.role === "manager" && <button className="fp-icon" aria-label="Arbeitsweise einstellen" disabled={locked} onClick={() => setConfig(true)}><Settings2 size={19} /></button>}</div></div>
      {(error || mutation.error) && <p className="fp-notice error" role="alert">{error || mutation.error}<button className="fp-button" disabled={refreshing || mutation.busy} onClick={() => void select(selected.current)}>Aktualisieren</button></p>}
      {notice && <p role="status" className="fp-notice">{notice}</p>}
      {mutation.pending && <div className="fp-notice" role="status"><p>{mutation.pending.label} Die Bestätigung steht noch aus. Der ursprüngliche Vorgang bleibt erhalten.</p><button className="fp-button" disabled={mutation.busy || mutation.blocked} onClick={() => void mutation.retry()}>Vorgang erneut prüfen</button></div>}
      {!loaded && !error && <Loading />}
      {visit ? <><div className="fp-section-head"><div><button className="fp-text-button" disabled={locked} onClick={() => keep(null)}><ChevronLeft size={16} /> Alle Besuche</button><h3>{visitLabel(visit)}</h3><small>{date(visit.created_at, venue.timezone)} · {visit.ended_at ? "Besuch beendet; Belege bleiben erhalten" : "Eigenständige Gruppe"}</small></div><button className="fp-button primary" disabled={locked} onClick={() => onCash(visit.id)}><Banknote size={17} /> Besuch kassieren</button></div><details className="fp-visit-people-details"><summary>Gäste, Namen & Plätze ({visit.tabs.filter(tab=>tab.kind==="guest").length})</summary><div className="fp-visit-people">{visit.tabs.map(tab => <div className="fp-visit-person" key={tab.id}><div><strong>{tabName(tab)}</strong><small>{resources.find(row => row.id === tab.current_table_id)?.name ?? "Ohne Tisch"}{tab.kind === "guest" ? tab.present ? " · anwesend" : " · gegangen" : " · gemeinsam bestellt"}</small></div><div className="fp-inline wrap"><button className="fp-button" disabled={locked} onClick={() => onCash(visit.id, tab.id)} aria-label={`${tabName(tab)} kassieren`}>Kassieren</button>{!visit.ended_at && <button className="fp-button" disabled={locked} onClick={() => setEditing(tab)} aria-label={`${tabName(tab)} bearbeiten`}>Name & Platz</button>}</div></div>)}</div></details>{!visit.ended_at && <button className="fp-text-button" disabled={locked} onClick={() => setEnding(true)}>Besuch beenden</button>}</> : <><div className="fp-two"><Field label="Geladene Besuche durchsuchen"><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Gast, Besuch oder Tisch …" /></Field><label className="fp-check"><input type="checkbox" checked={includeEnded} disabled={locked} onChange={event => setIncludeEnded(event.target.checked)} /> Auch beendete Besuche</label></div>{settings.workflow!=="counter"&&<Field label="Ort filtern"><select value={placeFilter} disabled={locked} onChange={event=>setPlaceFilter(event.target.value)}><option value="">Alle Orte und Theke</option>{resources.filter(row=>row.kind==="table").map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>}<div className="fp-visit-grid">{settings.workflow==="guest"?filtered.flatMap(value=>value.tabs.filter(tab=>tab.kind==="guest").map(tab=><button className="fp-visit-card" key={tab.id} disabled={locked} onClick={()=>void select(value.id).then(()=>setGuestId(tab.id))}><Users size={19}/><strong>{tabName(tab)}</strong><span>{visitLabel(value)}</span><small>{resources.find(row=>row.id===tab.current_table_id)?.name??"Ohne Tisch"}</small></button>)):filtered.map(value => <button className="fp-visit-card" key={value.id} disabled={locked} onClick={() => void select(value.id)}><Users size={19} /><strong>{visitLabel(value)}</strong><span>{value.tabs.filter(tab => tab.kind === "guest").map(tab => tabName(tab)).join(" · ")}</span><small>{[...new Set(value.tabs.map(tab => resources.find(row => row.id === tab.current_table_id)?.name).filter(Boolean))].join(" · ") || "Ohne Tisch"} · {value.ended_at ? "Beendet" : "Offen"}</small></button>)}</div>{loaded && !filtered.length && <Empty title="Platz für deine Gäste">Eröffne einen Besuch ohne Anmeldung oder Namenspflicht.{page.has_more ? " Weitere Besuche können nachgeladen werden." : ""}</Empty>}{page.has_more && <button className="fp-button" disabled={locked} onClick={() => void more()}>Weitere Besuche laden</button>}</>}
    </section>
    {visit && !visit.ended_at && <OrderComposer key={`composer:${visit.id}`} items={items} resources={resources} venueId={venue.id} initialTable="" confirmWarnings endpoint={`/gastro/venues/${venue.id}/service-visits/${visit.id}/rounds`} round={{ id: visit.id, version: visit.version, label: visitLabel(visit), tableId: visit.tabs.find(tab => tab.id === guestId)?.current_table_id ?? null, tabs: visit.tabs.map(tab => ({ id: tab.id, label: tabName(tab), version: tab.version, active: !visit.ended_at && (tab.kind === "shared" || tab.present) })), activeId: guestId, disabled: mutationLocked, onSelect: setGuestId, onAdd: () => void addGuest(), onBusyChange: onRoundBusyChange, onDone: async () => { await reload(); await onChanged(); setHistoryRevision(value=>value+1); setNotice("Die ganze Runde wurde gesendet. Die Bons bleiben je Gast getrennt nachvollziehbar."); } }} />}
    {visit && <VisitHistory key={`history:${visit.id}`} visit={visit} venue={venue} members={members} onChanged={async () => { await reload(); await onChanged(); }} onCash={onCash} revision={visit.version + historyRevision} />}
    {creating && <Modal title="Neuen Besuch eröffnen" closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setCreating(false); }}><p>Eine eigene Gruppe, auch wenn weitere Gäste denselben Tisch teilen.</p><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget), count = Number(form.get("guests")), tableId = str(form, "table") || null; void mutation.send("/service-visits", { label: str(form, "label"), ...(reservationId?{reservation_id:reservationId}:{}), tabs: [...Array.from({ length: count }, () => ({ kind: "guest", label: "", current_table_id: tableId, seat_label: "", present: true })), { kind: "shared", label: "", current_table_id: tableId, seat_label: "", present: false }] }, "Besuch eröffnet."); }}><fieldset disabled={locked} className="fp-cancellation-fieldset"><Field label="Tisch (optional)"><select name="table" value={createTable} onChange={event=>{setCreateTable(event.target.value);if(reservationId&&!reservations.some(row=>row.id===reservationId&&(row.table_ids??[row.table_id]).includes(event.target.value)))setReservationId("");}}><option value="">Ohne Tisch / Theke</option>{resources.filter(row => row.kind === "table").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>{reservations.some(row=>row.status==="seated")&&<Field label="Eingecheckte Reservierung (optional)"><select value={reservationId} onChange={event=>{setReservationId(event.target.value);const group=reservations.find(row=>row.id===event.target.value);if(group&&!((group.table_ids??[group.table_id]).includes(createTable)))setCreateTable(group.table_id);}}><option value="">Eigenständiger neuer Besuch</option>{reservations.filter(row=>row.status==="seated").map(row=><option key={row.id} value={row.id}>{row.guest_name} · {(row.table_ids??[row.table_id]).map(id=>resources.find(table=>table.id===id)?.name).join(" + ")}</option>)}</select></Field>}<div className="fp-two"><Field label="Gäste"><input name="guests" type="number" min={1} max={99} defaultValue={initialReservationId?reservations.find(row=>row.id===initialReservationId)?.guests??1:1} required /></Field><Field label="Gruppenname (optional)"><input name="label" maxLength={120} placeholder="Nummer genügt" /></Field></div><button className="fp-button primary wide">Besuch eröffnen</button></fieldset></form>{mutation.error && <p role="alert" className="fp-notice error">{mutation.error}</p>}</Modal>}
    {editing && <Modal title={`${tabName(editing)} · Name & Platz`} closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setEditing(null); }}><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void mutation.send(`/guest-tabs/${editing.id}/context`, { version: editing.version, label: str(form, "label"), current_table_id: str(form, "table") || null, seat_label: str(form, "seat"), present: editing.kind === "guest" && form.get("present") === "on", reason: str(form, "reason") }, "Gastkontext aktualisiert."); }}><fieldset disabled={locked} className="fp-cancellation-fieldset"><Field label="Gastname (optional)"><input name="label" defaultValue={editing.label} maxLength={120} /></Field><div className="fp-two"><Field label="Tisch (optional)"><select name="table" defaultValue={editing.current_table_id ?? ""}><option value="">Ohne Tisch</option>{resources.filter(row => row.kind === "table").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field><Field label="Sitzplatz (optional)"><input name="seat" defaultValue={editing.seat_label} maxLength={30} /></Field></div>{editing.kind === "guest" && <label className="fp-check"><input name="present" type="checkbox" defaultChecked={editing.present} /> Gast ist anwesend</label>}<Field label="Grund der Änderung"><input name="reason" minLength={3} maxLength={500} defaultValue="Gastangaben aktualisiert" required /></Field><p>Frühere Bons und bestätigte Zahlungen bleiben unverändert.</p><button className="fp-button primary wide">Gastangaben speichern</button></fieldset></form>{mutation.error && <p role="alert" className="fp-notice error">{mutation.error}</p>}</Modal>}
    {ending && visit && <Modal title="Besuch beenden" closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setEnding(false); }}><p>Die Gäste gelten danach als gegangen. Offene Forderungen und Erstattungen bleiben in der Kasse erhalten.</p><form onSubmit={event => { event.preventDefault(); void mutation.send(`/service-visits/${visit.id}/end`, { version: visit.version, reason: str(new FormData(event.currentTarget), "reason") }, "Besuch beendet."); }}><fieldset className="fp-cancellation-fieldset" disabled={locked}><Field label="Grund"><input name="reason" minLength={3} maxLength={500} defaultValue="Gäste sind gegangen" required /></Field><button className="fp-button primary wide">Gäste als gegangen markieren</button></fieldset></form>{mutation.error && <p role="alert">{mutation.error}</p>}</Modal>}
    {config && <Modal title="Arbeitsweise im Betrieb" closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setConfig(false); }}><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void mutation.send("/service-settings", { version: settings.version, workflow: str(form, "workflow"), guest_label_mode: str(form, "guest_label_mode") }, "Arbeitsweise gespeichert.", "PUT"); }}><fieldset className="fp-cancellation-fieldset" disabled={locked}><Field label="Standardansicht"><select name="workflow" defaultValue={settings.workflow}>{Object.entries(serviceWorkflows).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field><Field label="Gäste anzeigen als"><select name="guest_label_mode" defaultValue={settings.guest_label_mode}><option value="number">Gastnummer</option><option value="name_or_number">Name, sonst Gastnummer</option><option value="seat_or_number">Sitzplatz, sonst Gastnummer</option></select></Field><p>Neue Einstiege verwenden diese Vorgabe. Bestehende Besuche und Bons werden nicht verändert. Theke unterstützt derzeit Kassieren nach Servieren.</p><button className="fp-button primary wide">Arbeitsweise speichern</button></fieldset></form>{mutation.error && <p role="alert">{mutation.error}</p>}</Modal>}
  </div>;
}

function VisitHistory({ visit, venue, members, onCash, onChanged, revision }: { visit: ServiceVisit; venue: Venue; members: Member[]; onCash: (visitId: string, guestId?: string) => void; onChanged: () => Promise<void>; revision: number }) {
  const [rounds, setRounds] = useState<ServicePage<ServiceRound>>({ items: [], next_before: null, has_more: false });
  const [history, setHistory] = useState<ServicePage<ServiceCommand>>({ items: [], next_before: null, has_more: false });
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const live = useRef(false);
  const load = useCallback(async () => {
    const scope = identity();
    const [nextRounds, nextHistory] = await Promise.all([venueApi<ServicePage<ServiceRound>>(venue.id, `/service-visits/${visit.id}/rounds?limit=50`), venueApi<ServicePage<ServiceCommand>>(venue.id, `/service-visits/${visit.id}/history?limit=50`)]);
    if (!live.current || identity() !== scope) return;
    setRounds(nextRounds); setHistory(nextHistory); setError("");
  }, [venue.id, visit.id]);
  useEffect(() => { live.current = true; void load().catch(cause => { if (live.current) setError(message(cause)); }); return () => { live.current = false; }; }, [load, revision]);
  async function more(kind: "rounds" | "history") {
    const page = kind === "rounds" ? rounds : history; if (!page.next_before || busy) return;
    const scope = identity(); setBusy(true);
    try {
      if (kind === "rounds") { const next = await venueApi<ServicePage<ServiceRound>>(venue.id, `/service-visits/${visit.id}/rounds?limit=50&before=${page.next_before}`); if (live.current && scope === identity()) setRounds(current => ({ ...next, items: [...current.items, ...next.items] })); }
      else { const next = await venueApi<ServicePage<ServiceCommand>>(venue.id, `/service-visits/${visit.id}/history?limit=50&before=${page.next_before}`); if (live.current && scope === identity()) setHistory(current => ({ ...next, items: [...current.items, ...next.items] })); }
    } catch (cause) { if (scope === identity()) setError(message(cause)); }
    finally { if (scope === identity()) setBusy(false); }
  }
  return <section className="fp-panel fp-visit-history"><div className="fp-section-head"><h2>Runden & Verlauf</h2><button className="fp-button" onClick={() => void load().catch(cause => setError(message(cause)))}>Verlauf aktualisieren</button></div>{error && <p role="alert">{error}</p>}{rounds.items.map(round => <details className="fp-run" key={round.id}><summary>Runde {round.number} · {time(round.created_at, venue.timezone)} · {round.children.length} Bons</summary>{round.children.map(child => <div className="fp-visit-person" key={child.order_id}><div><strong>{child.label_snapshot} · {child.number}</strong><small>{labels[child.order.fulfillment_status] ?? child.order.fulfillment_status} · {labels[child.order.payment_status] ?? child.order.payment_status}</small><small>Original {money(child.order.total_cents + child.order.tip_cents)}</small></div><button className="fp-button" onClick={() => onCash(visit.id, child.guest_tab_id)}>Kassieren / Zahlungen</button><OrderCancellationButton venue={venue} members={members} order={child.order} onChanged={async () => { await onChanged(); await load(); }} /></div>)}</details>)}{rounds.has_more && <button className="fp-button" disabled={busy} onClick={() => void more("rounds")}>Weitere Runden laden</button>}<details className="fp-run"><summary>Besuchsverlauf</summary>{history.items.map(entry => <div className="fp-list-row" key={entry.id}><div><strong>{entry.reason || ({ "visit_created": "Besuch eröffnet", "tab_created": "Gast hinzugefügt", "round_created": "Runde gesendet", "tab_context_changed":"Gastangaben geändert", "visit_ended":"Besuch beendet", "units_assigned":"Positionen neu zugeordnet" }[entry.kind] ?? "Vorgang gespeichert")}</strong><small>{date(entry.created_at, venue.timezone)} · {time(entry.created_at, venue.timezone)} · {members.find(member => member.user_id === entry.actor_id)?.full_name ?? "Bedienung"}</small><AssignmentHistory entry={entry} visit={visit} rounds={rounds.items}/></div></div>)}{history.has_more && <button className="fp-button" disabled={busy} onClick={() => void more("history")}>Weitere Verlaufseinträge laden</button>}</details></section>;
}

function AssignmentHistory({ entry, visit, rounds }: { entry: ServiceCommand; visit: ServiceVisit; rounds: ServiceRound[] }) {
  if (entry.kind !== "units_assigned" || !Array.isArray(entry.result?.assignments)) return null;
  const assignments = entry.result.assignments as AssignedUnit[];
  const tabLabel = (id: string | null) => { const tab = visit.tabs.find(value => value.id === id); return tab ? guestTabLabel(tab) : id ? `Gastkonto ${id.slice(0, 8)}` : "Ohne Gastzuordnung"; };
  return <ul>{assignments.map(value => {
    const child = rounds.flatMap(round => round.children).find(row => row.order_id === value.order_id);
    const line = child?.order.lines.find(row => row.line_id === value.line_id);
    return <li key={value.id}>{child?.number ?? `Bon ${value.order_id.slice(0, 8)}`} · {line?.name ?? `Position ${value.line_id.slice(0, 8)}`} · Stück {value.unit + 1}: {tabLabel(value.before_tab_id)} → {tabLabel(value.guest_tab_id)} · Stand {value.version}</li>;
  })}</ul>;
}
