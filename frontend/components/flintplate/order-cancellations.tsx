"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, History, RefreshCw, ShieldCheck } from "lucide-react";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { CANCELLATION_PATH, CANCELLATION_PENDING, cancellationBlockers, cancellationPages, cancellationReasons, cancelledQuantity, remainingOrderQuantity, type CancellationExecution, type CancellationPreview, type CancellationReason, type CancellationRequest, type CancellationSelection } from "@/lib/flintplate-cancellations";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { day, labels, message, money, time, venueApi, type Member, type Order, type Venue } from "@/lib/flintplate";
import { lineStationName } from "@/lib/flintplate-stations";
import { Empty, Field, Modal, Tag, useLive } from "./shared";

const person = (id: string | null, members: Member[]) => id ? members.find(member => member.user_id === id)?.full_name ?? `Person ${id.slice(0, 8)}` : "System";
const reason = (value: string) => cancellationReasons[value as CancellationReason] ?? value;
const when = (value: string, venue: Venue) => `${day(value, venue.timezone)} · ${time(value, venue.timezone)}`;

function PendingNotice({ mutation }: { mutation: ReturnType<typeof useVenueMutation> }) {
  return <>{mutation.error && <p role="alert" className="fp-notice error">{mutation.error}</p>}{mutation.pending && <div className="fp-notice" role="status"><p>Die Bestätigung für „{mutation.pending.label}“ steht aus. Auswahl und Vorgangs-ID bleiben erhalten.</p><button className="fp-button" disabled={mutation.busy} onClick={() => void mutation.retry()}><RefreshCw size={16} /> Stornovorgang erneut prüfen</button></div>}</>;
}

function Preview({ value, historical = false }: { value: CancellationPreview; historical?: boolean }) {
  const credit = value.money.unpaid_credit_cents;
  const refund = value.money.refund_due_cents;
  return <div className="fp-cancellation-preview">{historical&&<p className="fp-description">Geprüfte Wirkung zum Antragszeitpunkt. Den aktuellen Auszahlungsstand zeigt die Kasse.</p>}
    <div className="fp-total"><span>Ausgewählter Stornobetrag</span><strong>{money(value.gross_cents)}</strong></div><small>Enthaltener Steueranteil: {money(value.tax_cents)}</small>
    {value.lines.map(line => <div className="fp-list-row" key={line.line_id}><div><strong>{line.quantity}× {line.name}</strong><small>{labels[line.preparation_status] ?? line.preparation_status} · {line.kind !== "product" ? "Keine automatische Lagerbuchung" : line.stock_effect === "consumption_retained" ? "Bereits erfasster Verbrauch bleibt bestehen" : "Noch kein Verbrauch für diese Auswahl erfasst"}</small>{["packaging", "deposit"].includes(line.kind) && <small>{line.kind === "deposit" ? "Pfand" : "Verpackung"} separat ausgewählt</small>}</div><strong>{money(line.gross_cents)}</strong></div>)}
    {typeof credit === "number" && <p>Offene Forderung wird um <strong>{money(credit)}</strong> vermindert.</p>}
    {typeof refund === "number" && <p>Rückzahlungsanspruch: <strong>{money(refund)}</strong>. Eine Auszahlung ist damit noch nicht bestätigt.</p>}
    {cancellationBlockers(value).map((blocker,index)=><p className="fp-notice error" key={`blocker-${index}`}>Freigabe gesperrt: {blocker}</p>)}
    {value.warnings.map((warning, index) => <p className="fp-notice" key={index}>{warning}</p>)}
    <p className="fp-description">Originalpositionen und Preise bleiben dokumentiert. Ein Storno bucht keine Zutaten oder fertigen Speisen automatisch ins Lager zurück.</p>
  </div>;
}

export function OrderCancellationDialog({ venue, orderId, initialOrder, members, onClose, onChanged, startNew = false }: { venue: Venue; orderId: string; initialOrder?: Order; members: Member[]; onClose: () => void; onChanged: () => Promise<unknown>; startNew?: boolean }) {
  const [order, setOrder] = useState<Order | null>(initialOrder ?? null);
  const [requests, setRequests] = useState<CancellationRequest[]>([]);
  const [mode, setMode] = useState<"history" | "new">(startNew ? "new" : "history");
  const [whole, setWhole] = useState(false);
  const [tip, setTip] = useState(false);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [code, setCode] = useState<CancellationReason | "">("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<{ result: CancellationPreview; selection: CancellationSelection } | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef(false);
  const valid = useRef(true);
  const requestVersion = useRef(0);
  const base = `/orders/${orderId}/cancellations`;
  const load = useCallback(async () => {
    const version = ++requestVersion.current, token = auth.getAccess();
    const [nextOrder, nextRequests] = await Promise.all([venueApi<Order>(venue.id, `/orders/${orderId}`), cancellationPages<CancellationRequest>(venue.id, `/orders/${orderId}/cancellations`)]);
    if (!active.current || !valid.current || version !== requestVersion.current || token !== auth.getAccess()) return;
    setOrder(nextOrder); setRequests(nextRequests); setLoading(false);
  }, [venue.id, orderId]);
  const mutation = useVenueMutation(venue.id, CANCELLATION_PENDING, CANCELLATION_PATH, async () => { await load(); await onChanged(); setPreview(null); setMode("history"); });
  useEffect(() => {
    active.current = true; valid.current = true;
    const clear = () => { valid.current = false; requestVersion.current++; setOrder(null); setRequests([]); setPreview(null); setError("Bitte erneut persönlich anmelden."); };
    const storage = (event: StorageEvent) => { if (event.key?.includes("token") || event.key === null) clear(); };
    window.addEventListener(AUTH_CHANGED_EVENT, clear); window.addEventListener("storage", storage);
    void Promise.resolve().then(() => load()).catch(cause => { if (active.current && valid.current) { setError(message(cause)); setLoading(false); } });
    return () => { active.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); window.removeEventListener("storage", storage); };
  }, [load]);
  const locked = loading || previewing || mutation.busy || !mutation.ready || mutation.blocked || !!mutation.pending;
  async function showPreview() {
    if (!order || !code || locked) return;
    const selection: CancellationSelection = { version: order.version, whole_order: whole, include_tip: tip, lines: whole ? [] : Object.entries(quantities).filter(([, quantity]) => quantity > 0).map(([line_id, quantity]) => ({ line_id, quantity })), reason_code: code, note: note.trim() };
    const token = auth.getAccess();
    setPreviewing(true); setError(""); setNotice("");
    try {
      const result = await venueApi<CancellationPreview>(venue.id, `${base}/preview`, "POST", selection);
      if (active.current && valid.current && auth.getAccess() === token) setPreview({ result, selection });
    } catch (cause) { if (active.current && valid.current && auth.getAccess() === token) setError(message(cause)); }
    finally { if (active.current) setPreviewing(false); }
  }
  async function create() {
    if (!preview || locked || (venue.role === "manager" && cancellationBlockers(preview.result).length > 0)) return;
    const approved = venue.role === "manager";
    if (await mutation.send(base, { ...preview.selection, preview_hash: preview.result.preview_hash, approve: approved }, `${approved ? "Storno" : "Stornoantrag"} · ${order?.number}`)) {
      setPreview(null); setQuantities({}); setNote(""); setTip(false); setWhole(false); setMode("history");
      setNotice(approved ? "Storno freigegeben und protokolliert. Etwaige Rückzahlungen werden in der Kasse separat bestätigt." : "Stornoantrag gesendet. Die Betriebsleitung entscheidet über die Freigabe.");
    }
  }
  async function decision(event: React.FormEvent<HTMLFormElement>, request: CancellationRequest) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const decision = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
    if (locked || (decision !== "approve" && decision !== "reject")) return;
    if (await mutation.send(`${base}/${request.id}/decision`, { version: request.order_version, preview_hash: request.preview.preview_hash, decision, note: String(form.get("decision_note") ?? "").trim() }, `${decision === "approve" ? "Freigabe" : "Ablehnung"} · ${request.order_number}`)) setNotice(decision === "approve" ? "Storno freigegeben. Eine erforderliche Auszahlung bleibt separat offen." : "Antrag begründet abgelehnt.");
  }
  return <Modal closeDisabled={mutation.busy || previewing} title={`${order?.number ?? "Bon"} · Storno & Verlauf`} onClose={() => { if (!mutation.busy && !previewing) onClose(); }}>
    <PendingNotice mutation={mutation} />{error && <p role="alert" className="fp-notice error">{error}<button className="fp-button" disabled={locked} onClick={() => { setPreview(null); setError(""); void Promise.resolve().then(() => load()).catch(cause => setError(message(cause))); }}>Aktuellen Bonstand laden</button></p>}{notice && <p role="status" className="fp-notice">{notice}</p>}
    {loading && <p role="status">Bon und Stornohistorie werden geladen …</p>}
    {order && <>
      <div className="fp-tabs" aria-label="Bonkorrektur"><button className={mode === "history" ? "active" : ""} disabled={locked} onClick={() => setMode("history")}>Bon & Verlauf</button><button className={mode === "new" ? "active" : ""} disabled={locked} onClick={() => setMode("new")}>{venue.role === "manager" ? "Storno erfassen" : "Storno anfragen"}</button></div>
      {mode === "new" && <>
        {!preview ? <form onSubmit={event => { event.preventDefault(); void showPreview(); }}>
          <fieldset disabled={locked} className="fp-cancellation-fieldset"><legend>Positionen und Grund</legend>
            <label className="fp-check"><input type="checkbox" checked={whole} onChange={event => setWhole(event.target.checked)} /> Gesamten verbleibenden Bon auswählen</label>
            {order.lines.map(line => { const remaining = remainingOrderQuantity(order, line.line_id); return <div className="fp-cancellation-line" key={line.line_id}><div><strong>{line.name}</strong><small>{line.quantity} ursprünglich · {cancelledQuantity(order, line.line_id)} storniert · {remaining} auswählbar</small><small>{labels[line.preparation_status] ?? line.preparation_status} · {lineStationName(line)} · Original {money(line.total_cents)}</small>{line.kind !== "product" && <Tag>{line.kind === "deposit" ? "Pfand" : line.kind === "packaging" ? "Verpackung" : "Eigene Bonposition"}</Tag>}</div><Field label={`Stornomenge ${line.name}`}><input type="number" min={0} max={remaining} step={1} disabled={whole || remaining === 0} value={whole ? remaining : quantities[line.line_id] ?? 0} onChange={event => setQuantities(current => ({ ...current, [line.line_id]: Number(event.target.value) }))} /></Field></div>; })}
            {order.tip_cents > 0 && <label className="fp-check"><input type="checkbox" checked={tip} onChange={event => setTip(event.target.checked)} /> Trinkgeld ausdrücklich einbeziehen (ursprünglich {money(order.tip_cents)})</label>}
            <Field label="Stornogrund"><select required value={code} onChange={event => setCode(event.target.value as CancellationReason | "")}><option value="">Grund wählen</option>{Object.entries(cancellationReasons).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
            <Field label="Begründung für das Journal"><textarea required minLength={3} maxLength={500} rows={3} value={note} onChange={event => setNote(event.target.value)} placeholder="Was ist passiert?" /></Field>
            <p className="fp-description">{venue.role === "manager" ? "Du kannst selbst freigeben. Dein Konto und die Begründung werden ausdrücklich protokolliert." : "Dein Antrag ändert den Bon noch nicht. Nur die Betriebsleitung darf das Storno freigeben."}</p>
            <button className="fp-button primary wide" disabled={!whole && !tip && !Object.values(quantities).some(quantity => quantity > 0)}>{previewing ? "Wirkung wird geprüft …" : "Stornobetrag und Folgen prüfen"}</button>
          </fieldset>
        </form> : <><Preview value={preview.result} /><div className="fp-form-box"><strong>{reason(preview.selection.reason_code)}</strong><p>{preview.selection.note}</p></div><div className="fp-inline wrap"><button className="fp-button" disabled={locked} onClick={() => setPreview(null)}>Auswahl bearbeiten</button><button className="fp-button danger" disabled={locked || (venue.role === "manager" && cancellationBlockers(preview.result).length > 0)} onClick={() => void create()}>{venue.role === "manager" ? "Storno verbindlich freigeben" : "Stornoantrag senden"}</button></div></>}
      </>}
      {mode === "history" && <>
        <div className="fp-total"><span>Ursprünglicher Bon</span><strong>{money(order.total_cents)}</strong></div>
        <p>{when(order.created_at, venue)} · {labels[order.status] ?? order.status} · Version {order.version}</p>
        {order.lines.map(line => <div className="fp-list-row" key={line.line_id}><div><strong>{line.quantity}× {line.name}</strong><small>{cancelledQuantity(order, line.line_id)} storniert · {remainingOrderQuantity(order, line.line_id)} verbleibend</small></div><strong>{money(line.total_cents)}</strong></div>)}
        <h3>Stornoanträge und Entscheidungen</h3>
        {!requests.length && <Empty title="Noch kein Stornovorgang für diesen Bon" />}
        {requests.map(request => <article className="fp-cancellation-history" key={request.id}>
          <div className="fp-section-head"><div><strong>{reason(request.reason_code)}</strong><small>Antrag von {person(request.requester_id, members)} · {when(request.created_at, venue)}</small></div><Tag tone={request.execution ? "green" : request.decision ? "neutral" : "amber"}>{request.execution ? "Storniert" : request.decision ? "Abgelehnt" : "Freigabe ausstehend"}</Tag></div>
          <p>{request.note}</p><Preview value={request.preview} historical />
          {request.decision && <div className="fp-form-box"><strong>{request.decision.decision === "approve" ? "Freigegeben" : "Abgelehnt"} von {person(request.decision.actor_id, members)}</strong><small>{when(request.decision.created_at, venue)}{request.decision.self_approved ? " · Eigene Freigabe ausdrücklich protokolliert" : ""}</small><p>{request.decision.note}</p></div>}
          {request.execution && <p>Stornobeleg {request.execution.id.slice(0, 8)} · {when(request.execution.created_at, venue)}{request.execution.checkout_reconciliation_required ? " · Kassenadapter-Abgleich erforderlich" : ""}{request.execution.kitchen_required ? request.execution.acknowledgement ? ` · Küche bestätigt durch ${person(request.execution.acknowledgement.actor_id, members)} (${when(request.execution.acknowledgement.created_at, venue)})` : " · Küchenbestätigung ausstehend" : ""}</p>}
          {!request.decision && venue.role === "manager" && <form onSubmit={event => void decision(event, request)}><fieldset disabled={locked} className="fp-cancellation-fieldset"><Field label={`Entscheidungsbegründung ${request.id.slice(0, 8)}`}><textarea name="decision_note" required minLength={3} maxLength={500} rows={2} /></Field>{order.version !== request.order_version && <p className="fp-notice">Der Bon wurde seit dem Antrag geändert. Antrag ablehnen und die Auswahl mit dem aktuellen Stand erneut prüfen.</p>}<div className="fp-inline wrap"><button className="fp-button" type="submit" name="decision" value="reject">Antrag ablehnen</button><button className="fp-button danger" type="submit" name="decision" value="approve" disabled={order.version !== request.order_version || cancellationBlockers(request.preview).length > 0}><ShieldCheck size={16} /> Antrag freigeben</button></div></fieldset></form>}
        </article>)}
      </>}
    </>}
  </Modal>;
}

export function CancellationQueue({ venue, members, onChanged, compact = false, onOpen }: { venue: Venue; members: Member[]; onChanged: () => Promise<unknown>; compact?: boolean; onOpen?: () => void }) {
  const [rows, setRows] = useState<CancellationRequest[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const active = useRef(false), version = useRef(0);
  const load = useCallback(async (before?: string) => {
    const id = ++version.current, token = auth.getAccess();
    setLoading(true);
    try {
      const page = await venueApi<CancellationRequest[]>(venue.id, `/cancellations?pending_only=true&limit=${compact ? 1 : 50}${before ? `&before=${before}` : ""}`);
      if (!active.current || id !== version.current || token !== auth.getAccess()) return;
      if (page.length && page.at(-1)?.id === before) throw new Error("Die nächste Antragsseite konnte nicht geladen werden.");
      setRows(current => before ? [...new Map([...current, ...page].map(request => [request.id, request])).values()] : page); setMore(page.length === 50); setError("");
    } catch (cause) { if (active.current && id === version.current && token === auth.getAccess()) setError(message(cause)); }
    finally { if (active.current && id === version.current) setLoading(false); }
  }, [venue.id, compact]);
  const mutation = useVenueMutation(venue.id, CANCELLATION_PENDING, CANCELLATION_PATH, async () => { await load(); await onChanged(); });
  useEffect(() => { active.current = true; void Promise.resolve().then(() => load()); const clear = () => { version.current++; setRows([]); setSelected(null); }; window.addEventListener(AUTH_CHANGED_EVENT, clear); return () => { active.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); }; }, [load]);
  useLive(async () => { if (!selected && (compact || !more) && !mutation.pending) await load(); }, 15000);
  if (compact) return rows.length || mutation.pending || mutation.error || error ? <div className="fp-notice fp-cancellation-attention" role="status"><span>{mutation.pending ? "Ein Stornovorgang wartet auf Bestätigung." : mutation.error || error || "Stornoanträge warten auf eine Entscheidung."}</span><button className="fp-button" onClick={onOpen}>{mutation.pending ? "Ausstehenden Stornovorgang öffnen" : "Stornoanträge öffnen"}</button></div> : null;
  return <section className="fp-panel">
    <div className="fp-section-head"><div><h2>Stornoanträge</h2><p>{venue.role === "manager" ? "Offene Anträge prüfen und begründet entscheiden." : "Anträge bleiben bis zur Entscheidung der Betriebsleitung sichtbar."}</p></div><div className="fp-inline"><Tag tone={rows.length ? "amber" : "neutral"}>{rows.length} geladen</Tag><button className="fp-button" disabled={loading} onClick={()=>void load()}>Anträge aktualisieren</button></div></div>
    {!selected && <PendingNotice mutation={mutation} />}{error && <p role="alert" className="fp-notice error">{error}</p>}
    {rows.map(request => <div className="fp-history-order" key={request.id}><div><strong>{request.order_number} · {money(request.preview.gross_cents)}</strong><small>{reason(request.reason_code)} · {person(request.requester_id, members)} · {when(request.created_at, venue)}</small><small>{request.note}</small></div><button className="fp-button" onClick={() => setSelected(request.order_id)}>{venue.role === "manager" ? "Antrag prüfen" : "Antrag ansehen"}</button></div>)}
    {!rows.length && !loading && !error && <Empty title="Keine offenen Stornoanträge" />}
    {loading && <p role="status">Stornoanträge werden geladen …</p>}{more && <button className="fp-button" disabled={loading} onClick={() => void load(rows.at(-1)?.id)}>Weitere Anträge laden</button>}
    {selected && <OrderCancellationDialog venue={venue} orderId={selected} members={members} onClose={() => setSelected(null)} onChanged={async () => { await load(); await onChanged(); }} />}
  </section>;
}

export function KitchenCancellations({ venue, members, onChanged }: { venue: Venue; members: Member[]; onChanged: () => Promise<unknown> }) {
  const [rows, setRows] = useState<CancellationExecution[]>([]);
  const [error, setError] = useState("");
  const active = useRef(false);
  const load = useCallback(async () => { const token = auth.getAccess(); const next = await cancellationPages<CancellationExecution>(venue.id, "/cancellations/kitchen?unacknowledged=true"); if (active.current && token === auth.getAccess()) { setRows(next); setError(""); } }, [venue.id]);
  const mutation = useVenueMutation(venue.id, CANCELLATION_PENDING, CANCELLATION_PATH, async () => { await load(); await onChanged(); });
  useEffect(() => { active.current = true; void Promise.resolve().then(() => load()).catch(cause => { if (active.current) setError(message(cause)); }); const clear = () => setRows([]); window.addEventListener(AUTH_CHANGED_EVENT, clear); return () => { active.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); }; }, [load]);
  useLive(load, 10000);
  if (!rows.length && !error && !mutation.pending && !mutation.error) return null;
  return <section className="fp-panel fp-kitchen-cancellations"><h2><CircleAlert size={21} /> Stornos für Küche & Bar</h2><p>Diese Positionen wurden verbindlich storniert. Empfang nach Prüfung bestätigen; der Warenverbrauch bleibt dokumentiert.</p><PendingNotice mutation={mutation} />{error && <p role="alert" className="fp-notice error">{error}</p>}{rows.map(row => <article className="fp-cancellation-history" key={row.id}><div className="fp-section-head"><strong>{row.order_number} · {reason(row.reason_code)}</strong><Tag tone="amber">Bestätigung offen</Tag></div><p>{row.note}</p>{row.lines.map(line => <p key={line.line_id}><strong>{line.quantity}× {line.name}</strong> · {line.station} · {labels[line.preparation_status] ?? line.preparation_status}</p>)}<small>Freigegeben von {person(row.actor_id, members)} · {when(row.created_at, venue)}</small><button className="fp-button wide" disabled={mutation.busy || !!mutation.pending || !mutation.ready || mutation.blocked} onClick={() => void mutation.send(`/cancellations/${row.id}/ack`, {}, `Küchenbestätigung · ${row.order_number}`)}>Stornomeldung gelesen</button></article>)}</section>;
}

export function OrderCancellationButton({ venue, order, members, onChanged }: { venue: Venue; order: Order; members: Member[]; onChanged: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  return <><button className="fp-button" onClick={() => setOpen(true)} aria-label={`Storno und Verlauf für ${order.number}`}><History size={16} /> Storno & Verlauf</button>{open && <OrderCancellationDialog venue={venue} orderId={order.id} initialOrder={order} startNew={!["settled", "cancelled"].includes(order.status)} members={members} onClose={() => setOpen(false)} onChanged={onChanged} />}</>;
}
