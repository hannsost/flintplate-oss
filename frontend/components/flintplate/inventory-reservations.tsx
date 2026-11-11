"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, str, type Venue } from "@/lib/flintplate";
import { stockMicros, stockQuantity, stockUnits, type InventorySnapshot } from "@/lib/flintplate-inventory";
import { reservationApi, reservationStatus, type StockReservation } from "@/lib/flintplate-reservations";
import { Empty, Field, Modal, Tag, useLive } from "./shared";

interface Pending { path: string; payload: Record<string, unknown> }
interface Dialog { key: string; kind: "reserve" | "release" | "consume"; reservation?: StockReservation }
const PREFIX = "flintplate:inventory-reservation-pending:v1:";
const CHANGED = "flintplate-inventory-reservation-pending-changed";

export function InventoryReservations({ venue, stock, onChange }: { venue: Venue; stock: InventorySnapshot; onChange: () => Promise<unknown> }) {
  const [rows, setRows] = useState<StockReservation[]>([]);
  const [showClosed, setShowClosed] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [balanceKey, setBalanceKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pendingRef = useRef<Pending | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const scope = useRef<string | null>(null);
  const currentScope = () => { const user = auth.getUser(); return user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null; };
  const reload = useCallback(async () => { const next = await reservationApi<StockReservation[]>(venue.id); if (mounted.current) setRows(next); }, [venue.id]);
  useEffect(() => {
    mounted.current = true;
    const user = auth.getUser();
    const key = user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null;
    scope.current = key;
    const read = () => {
      try {
        const raw = key ? localStorage.getItem(key) : null;
        const value: unknown = raw ? JSON.parse(raw) : null;
        if (value !== null && (typeof value !== "object" || !("path" in value) || typeof value.path !== "string" || !/^(|\/[a-f0-9-]+\/close)$/.test(value.path) || !("payload" in value) || !value.payload || typeof value.payload !== "object" || !("request_key" in value.payload) || typeof value.payload.request_key !== "string")) throw new Error("Der ausstehende Reservierungsauftrag konnte nicht sicher gelesen werden. Bitte den Service kontaktieren.");
        pendingRef.current = value as Pending | null; setPending(pendingRef.current);
      } catch (cause) { setBlocked(true); setError(message(cause)); }
    };
    const changed = () => { const next = auth.getUser(); const nextKey = next?.sub ? PREFIX + encodeURIComponent(JSON.stringify([next.tenant_id, next.sub, venue.id])) : null; if (nextKey !== key) { mounted.current = false; setBlocked(true); setRows([]); setDialog(null); pendingRef.current = null; setPending(null); setError("Bitte erneut persönlich anmelden."); } };
    const storage = (event: StorageEvent) => { changed(); if (event.key === key && mounted.current) read(); };
    read(); void reload().catch(cause => { if (mounted.current) setError(message(cause)); });
    window.addEventListener(CHANGED, read); window.addEventListener(AUTH_CHANGED_EVENT, changed); window.addEventListener("storage", storage);
    return () => { mounted.current = false; window.removeEventListener(CHANGED, read); window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", storage); };
  }, [reload, venue.id]);
  useLive(reload);

  async function execute(request: Pending) {
    if (inFlight.current || blocked) return;
    const key = currentScope();
    if (!mounted.current || !key || key !== scope.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const retry = pendingRef.current !== null;
    try {
      const previous = localStorage.getItem(key);
      if (previous && previous !== JSON.stringify(request)) { window.dispatchEvent(new Event(CHANGED)); setError("Zuerst den bereits ausstehenden Reservierungsauftrag prüfen."); return; }
      localStorage.setItem(key, JSON.stringify(request));
    } catch { setError("Der Browser kann diese Buchung nicht absichern. Bitte Browserspeicher prüfen."); return; }
    pendingRef.current = request; setPending(request); inFlight.current = true; setBusy(true); setError("");
    try {
      await reservationApi(venue.id, request.path, "POST", request.payload);
      if (!mounted.current || currentScope() !== key) return;
      localStorage.removeItem(key); pendingRef.current = null; setPending(null); window.dispatchEvent(new Event(CHANGED));
      setDialog(null); setNotice("Reservierungsauftrag bestätigt."); await Promise.all([reload(), onChange()]);
    } catch (cause) {
      if (!mounted.current || currentScope() !== key) return;
      if (!retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) { localStorage.removeItem(key); pendingRef.current = null; setPending(null); window.dispatchEvent(new Event(CHANGED)); }
      setError(message(cause));
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  const available = stock.balances.filter(balance => stockMicros(balance.available_quantity) > BigInt(0));
  const active = rows.filter(row => row.status === "active" || row.status === "undercovered");
  const visible = showClosed ? rows : active;
  const locked = busy || !!pending || blocked;
  const chosen = stock.balances.find(balance => balance.lot_id + "/" + balance.location_id === balanceKey);
  const unit = stock.items.find(item => item.id === chosen?.item_id)?.unit;
  function open(kind: Dialog["kind"], reservation?: StockReservation) {
    if (inFlight.current || pendingRef.current || blocked) return;
    setDialog({ kind, reservation, key: newRequestId() }); setError(""); setNotice("");
    setBalanceKey(available.length ? available[0].lot_id + "/" + available[0].location_id : "");
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) { await execute(pendingRef.current); return; }
    if (!dialog || locked) return;
    const form = new FormData(event.currentTarget);
    const base = { request_key: dialog.key, reason: str(form, "reason") };
    if (dialog.kind === "reserve") {
      const [lot_id, location_id] = balanceKey.split("/");
      await execute({ path: "", payload: { ...base, lot_id, location_id, quantity: str(form, "quantity"), duration_minutes: Number(str(form, "duration_minutes")) } });
    } else if (dialog.reservation) {
      await execute({ path: `/${dialog.reservation.id}/close`, payload: { ...base, kind: dialog.kind, usage_reference: dialog.kind === "consume" ? str(form, "usage_reference") : "" } });
    }
  }
  return <section className="fp-panel">
    <div className="fp-section-head"><div><h2>Bestand reservieren</h2><p>Eine Reservierung hält Ware für einen konkreten Zweck frei. Die physische Menge bleibt bis zum Verbrauch bestehen.</p></div><button className="fp-button" disabled={locked || !available.length} onClick={() => open("reserve")}><Plus size={16} /> Reservierung</button></div>
    {error && <p className="fp-notice error" role="alert">{error}</p>}{notice && <p className="fp-notice" role="status">{notice}</p>}
    {pending && <div className="fp-notice"><p>Ein Reservierungsauftrag wartet auf eindeutige Bestätigung. Seine ursprünglichen Angaben bleiben erhalten.</p><button className="fp-button" disabled={busy || blocked} onClick={() => void execute(pending)}>Ausstehenden Auftrag erneut prüfen</button></div>}
    {active.some(row => row.status === "undercovered") && <p className="fp-notice error" role="alert">Die tatsächliche Zählung deckt nicht alle Reservierungen. Fehlmengen prüfen und nicht mehr erfüllbare Reservierungen freigeben.</p>}
    <label className="fp-check"><input type="checkbox" checked={showClosed} onChange={event => setShowClosed(event.target.checked)} /> Auch abgeschlossene und abgelaufene Reservierungen anzeigen</label>
    {!visible.length ? <Empty title="Keine offenen Reservierungen">Ablauf gibt die Menge automatisch wieder frei. Eine Inventurzählung kann reservierte Ware als fehlend ausweisen.</Empty> : <div className="fp-table-wrap"><table><thead><tr><th>Zweck / Charge</th><th>Reserviert</th><th>Gedeckt / fehlt</th><th>Bis</th><th>Status</th><th>Aktion</th></tr></thead><tbody>{visible.map(row => {
      const lot = stock.lots.find(lot => lot.id === row.lot_id);
      const item = stock.items.find(item => item.id === lot?.item_id);
      return <tr key={row.id}><td><strong>{row.reason}</strong><small>{item?.name} · {lot?.code} · {stock.locations.find(location => location.id === row.location_id)?.name} · {stock.owners.find(owner => owner.id === lot?.owner_id)?.name}</small></td><td>{stockQuantity(row.quantity)} {stockUnits[item?.unit ?? "piece"]}</td><td>{row.status === "active" || row.status === "undercovered" ? <>{stockQuantity(row.covered_quantity)} gedeckt{stockMicros(row.shortfall_quantity) > BigInt(0) && <small>{stockQuantity(row.shortfall_quantity)} fehlen</small>}</> : "—"}</td><td>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short", timeZone: venue.timezone }).format(new Date(row.expires_at))}</td><td><Tag tone={row.status === "undercovered" || row.blocked || row.lot_expired ? "red" : "neutral"}>{reservationStatus[row.status]}</Tag>{row.blocked && <small>Charge gesperrt</small>}{row.lot_expired && <small>MHD überschritten</small>}</td><td>{(row.status === "active" || row.status === "undercovered") && <><button className="fp-button" disabled={locked} onClick={() => open("release", row)}>Freigeben</button><button className="fp-button" disabled={locked || !row.consumable} onClick={() => open("consume", row)}>Manuell verbrauchen</button></>}{row.closed_at && <small>{row.closure_reason}</small>}</td></tr>;
    })}</tbody></table></div>}
    <p>Deckung folgt stabil der Anlagezeit. Manueller Verbrauch ist für Eigenware bestimmt; Partnerware nach Freigabe über belegten Verkauf oder Partnerverlust buchen. Hier erscheinen die letzten 500 Reservierungen.</p>
    {dialog && <Modal title={dialog.kind === "reserve" ? "Bestand befristet reservieren" : dialog.kind === "release" ? "Reservierung freigeben" : "Reservierte Eigenware manuell verbrauchen"} onClose={() => { if (!busy) setDialog(null); }}><form key={dialog.key} onSubmit={submit}><fieldset disabled={locked} style={{ border: 0, margin: 0, padding: 0 }}>
      {dialog.kind === "reserve" ? <><Field label="Freie Charge und Lagerort"><select required value={balanceKey} onChange={event => setBalanceKey(event.target.value)}>{available.map(balance => <option key={balance.lot_id + balance.location_id} value={balance.lot_id + "/" + balance.location_id}>{stock.items.find(item => item.id === balance.item_id)?.name} · {stock.lots.find(lot => lot.id === balance.lot_id)?.code} · {stock.locations.find(location => location.id === balance.location_id)?.name} · {stockQuantity(balance.available_quantity)} frei</option>)}</select></Field><Field label="Zu reservierende Menge"><input type="number" name="quantity" min={unit === "piece" ? "1" : "0.000001"} max={chosen?.available_quantity} step={unit === "piece" ? "1" : "0.000001"} required /></Field><Field label="Automatische Freigabe nach Minuten"><input type="number" name="duration_minutes" min="1" max="525600" step="1" defaultValue="120" required /></Field></> : <p>{dialog.reservation?.reason} · {stockQuantity(dialog.reservation?.quantity ?? "0")} reserviert</p>}
      {dialog.kind === "consume" && <><Field label="Produktions- oder Verbrauchsbeleg"><input name="usage_reference" required minLength={3} maxLength={120} placeholder="z. B. Vorbereitung Buffet 14.09." /></Field><p>Die Ware wird jetzt aus dem Lager entnommen. Bereits über Rezeptur oder KDS verbrauchte Mengen hier nicht erneut buchen.</p></>}
      <Field label={dialog.kind === "reserve" ? "Konkreter Zweck" : "Begründung"}><input name="reason" required minLength={3} maxLength={300} /></Field>
    </fieldset><button className="fp-button primary" type="submit" disabled={busy || blocked}>{busy ? "Wird geprüft …" : pending ? "Ursprünglichen Auftrag erneut prüfen" : dialog.kind === "consume" ? "Verbrauch buchen" : dialog.kind === "release" ? "Freigeben" : "Reservieren"}</button></form></Modal>}
  </section>;
}
