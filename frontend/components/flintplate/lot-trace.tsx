"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, ShieldAlert } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, venueApi, type Order, type Venue } from "@/lib/flintplate";
import { inventoryApi, stockQuantity, stockUnits, type InventorySnapshot } from "@/lib/flintplate-inventory";
import { Field, Loading, Modal, Tag } from "./shared";

interface Trace { source_lot_id: string; affected_lot_ids: string[]; operation_ids: string[]; order_ids: string[]; truncated: boolean }
interface RecallRequest { request_key: string; reason: string }
const PREFIX = "flintplate:recall-pending:v1:";

export function LotTrace({ venue, lotId, inventory, onClose, onRecalled }: { venue: Venue; lotId: string; inventory: InventorySnapshot; onClose: () => void; onRecalled: () => void }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const pending = useRef<RecallRequest | null>(null);
  const sending = useRef(false);
  const source = inventory.lots.find(lot => lot.id === lotId);
  const getKey = () => {
    const user = auth.getUser();
    return user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id, lotId])) : null;
  };
  const initialKey = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    const user = auth.getUser();
    const key = user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id, lotId])) : null;
    initialKey.current = key;
    try {
      const raw = key ? localStorage.getItem(key) : null;
      if (raw) {
        const value: unknown = JSON.parse(raw);
        if (typeof value !== "object" || value === null || !("request_key" in value) || typeof value.request_key !== "string" || !("reason" in value) || typeof value.reason !== "string") throw new Error("Gespeicherter Rückruf konnte nicht gelesen werden.");
        pending.current = { request_key: value.request_key, reason: value.reason };
        setReason(value.reason);
        setUncertain(true);
      }
    } catch (cause) { setError(message(cause)); setRecoveryBlocked(true); }
    void inventoryApi<Trace>(venue.id, `/lots/${lotId}/trace`).then(result => { if (active) setTrace(result); }).catch(cause => { if (active) setError(message(cause)); });
    void venueApi<Order[]>(venue.id, "/orders?include_closed=true").then(result => { if (active) setOrders(result); }).catch(() => { /* Trace still exposes every authoritative order reference. */ });
    const clear = () => { active = false; pending.current = null; setReason(""); setTrace(null); setError("Die Anmeldung hat sich geändert. Bitte dieses Fenster schließen."); setUncertain(false); };
    const onStorage = () => {
      const current = auth.getUser();
      const currentKey = current?.sub ? PREFIX + encodeURIComponent(JSON.stringify([current.tenant_id, current.sub, venue.id, lotId])) : null;
      if (currentKey !== key) clear();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(AUTH_CHANGED_EVENT, clear);
    return () => { active = false; window.removeEventListener("storage", onStorage); window.removeEventListener(AUTH_CHANGED_EVENT, clear); };
  }, [venue.id, lotId]);

  async function recall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current || !trace || trace.truncated || completed || recoveryBlocked) return;
    const key = getKey();
    if (!key || key !== initialKey.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const payload = pending.current ?? { request_key: newRequestId(), reason: reason.trim() };
    try { localStorage.setItem(key, JSON.stringify(payload)); }
    catch { setError("Der Browser kann den Rückruf nicht absichern. Bitte Browserspeicher freigeben und erneut versuchen."); return; }
    pending.current = payload;
    const retry = uncertain;
    setUncertain(true);
    setBusy(true);
    sending.current = true;
    setError("");
    try {
      const result = await inventoryApi<Trace>(venue.id, `/lots/${lotId}/recall`, "POST", payload);
      if (getKey() !== key) return;
      localStorage.removeItem(key);
      pending.current = null;
      setTrace(result);
      setUncertain(false);
      setCompleted(true);
      onRecalled();
    } catch (cause) {
      if (getKey() !== key) return;
      if (!retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) {
        localStorage.removeItem(key);
        pending.current = null;
        setUncertain(false);
      }
      setError(message(cause));
    } finally { sending.current = false; setBusy(false); }
  }

  return <Modal title={`Charge ${source?.code ?? lotId.slice(0, 8)} · Rückverfolgung`} onClose={() => { if (!busy && !uncertain) onClose(); }}>
    {error && <p className="fp-notice error" role="alert">{error}</p>}
    {!trace ? !error && <Loading /> : <div className="fp-stack">
      <p>Von der Ausgangscharge über erfasste Produktionsbuchungen bis zu den betroffenen Bons.</p>
      <div className="fp-inline wrap"><Tag>{trace.affected_lot_ids.length} verbundene Chargen</Tag><Tag>{trace.operation_ids.length} Produktionsbuchungen</Tag><Tag>{trace.order_ids.length} betroffene Bons</Tag></div>
      {trace.truncated && <p className="fp-notice error" role="alert">Die Rückverfolgung überschreitet die automatische Grenze. Betriebsleitung und Support müssen den vollständigen Umfang prüfen; die automatische Sperre steht hier nicht zur Verfügung.</p>}
      <section><h3>Verbundene Chargen</h3>{trace.affected_lot_ids.map(id => {
        const lot = inventory.lots.find(entry => entry.id === id);
        const item = inventory.items.find(entry => entry.id === lot?.item_id);
        const owner = inventory.owners.find(entry => entry.id === lot?.owner_id);
        const balances = inventory.balances.filter(entry => entry.lot_id === id);
        return <article className="fp-trace-row" key={id}><div><strong>{item?.name ?? "Charge"} · {lot?.code ?? id}</strong><small>{id === lotId ? "Ausgangscharge" : "Abgeleitete Produktionscharge"} · {owner?.name ?? "Eigentümer siehe Lagerjournal"}</small>{balances.map(balance => <small key={balance.location_id}>{stockQuantity(balance.quantity)} {item ? stockUnits[item.unit] : "Einheiten"} · {inventory.locations.find(location => location.id === balance.location_id)?.name ?? "Lagerort"}</small>)}</div><Tag tone={completed || lot?.blocked ? "amber" : "neutral"}>{completed || lot?.blocked ? "Gesperrt" : "Erfasst"}</Tag></article>;
      })}</section>
      <section><h3>Betroffene Bons</h3>{trace.order_ids.length ? trace.order_ids.map(id => {
        const order = orders.find(entry => entry.id === id);
        return <div className="fp-trace-row" key={id}><div><strong>{order?.number ?? `Bon ${id}`}</strong>{order && <small>{order.lines.filter(line => line.kind === "product").map(line => `${line.quantity}× ${line.name}`).join(", ")}</small>}<small>Bonreferenz: {id}</small></div></div>;
      }) : <p>Für diese Charge sind noch keine Verbrauchsbuchungen mit Bonbezug erfasst.</p>}</section>
      {trace.operation_ids.length > 0 && <details><summary>Referenzen im Produktionsjournal</summary><ul className="fp-trace-references">{trace.operation_ids.map(id => <li key={id}>{id}</li>)}</ul></details>}
      {completed ? <p className="fp-notice" role="status"><Check size={19} /> Rückruf erfasst. {trace.affected_lot_ids.length} Chargen sind gesperrt.</p> : venue.role === "manager" && !trace.truncated && !recoveryBlocked && <form className="fp-tip-box" onSubmit={recall}><strong><ShieldAlert size={18} /> Charge und Folgechargen sperren</strong><p>Die Sperre umfasst den vorhandenen Bestand aller oben aufgeführten Chargen. Betroffene Bons bleiben dokumentiert.</p><Field label="Grund des Rückrufs"><textarea required minLength={3} maxLength={300} value={reason} disabled={busy || uncertain} onChange={event => setReason(event.target.value)} placeholder="Zum Beispiel konkrete Lieferantenmeldung und betroffene Liefercharge" /></Field>{uncertain && <p role="status">Die Bestätigung steht aus. Erneut prüfen verwendet dieselbe Rückruf-ID, auch nach erneutem Öffnen dieser Charge.</p>}<button className="fp-button danger" disabled={busy || reason.trim().length < 3}>{busy ? "Sperre wird geprüft …" : uncertain ? "Rückruf erneut prüfen" : `${trace.affected_lot_ids.length} Chargen sperren`}</button></form>}
    </div>}
  </Modal>;
}
