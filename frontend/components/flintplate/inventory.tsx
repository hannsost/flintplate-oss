"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRightLeft, ClipboardCheck, PackagePlus, Plus, RefreshCw, ScanSearch, ShieldAlert, Trash2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, str, type Venue } from "@/lib/flintplate";
import {
  formatStockMicros, inventoryApi, stockMicros, stockOperationNames, stockQuantity, stockUnits,
  type InventorySnapshot, type StockBalance, type StockOperation,
} from "@/lib/flintplate-inventory";
import { Empty, Field, Loading, Modal, Tag, useLive } from "./shared";
import { LotTrace } from "./lot-trace";
import { InventoryReservations } from "./inventory-reservations";

interface PendingBooking { endpoint: string; fields: Record<string, unknown>; kind: string }
const PENDING_PREFIX = "flintplate:inventory-pending:v1:";
const PENDING_CHANGED = "flintplate-inventory-pending-changed";

type Dialog =
  | { kind: "item" | "owner" | "location" | "receipt"; key: string }
  | { kind: "transfer" | "waste" | "count" | "quarantine"; key: string; balance: StockBalance; lotVersion: number };

export function InventoryPanel({ venue }: { venue: Venue }) {
  return <InventoryWorkspace key={venue.id} venue={venue} />;
}

function InventoryWorkspace({ venue }: { venue: Venue }) {
  const [data, setData] = useState<InventorySnapshot | null>(null);
  const [history, setHistory] = useState<StockOperation[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [tab, setTab] = useState<"stock" | "masters" | "history" | "reservations">("stock");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [traceLot, setTraceLot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingBooking | null>(null);
  const pendingRef = useRef<PendingBooking | null>(null);
  const scope = useRef<string | null>(null);
  const inFlight = useRef(false);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [showZero, setShowZero] = useState(false);
  const [receiptItem, setReceiptItem] = useState("");
  const [masterUnit, setMasterUnit] = useState("kg");
  const mounted = useRef(true);
  const manager = venue.role === "manager";

  const currentScope = () => {
    const user = auth.getUser();
    return user?.sub ? PENDING_PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null;
  };
  useEffect(() => {
    const user = auth.getUser();
    const key = user?.sub ? PENDING_PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null;
    scope.current = key;
    const read = () => {
      try {
        const raw = key ? localStorage.getItem(key) : null;
        const value: unknown = raw ? JSON.parse(raw) : null;
        if (value !== null && (typeof value !== "object" || !("endpoint" in value) || typeof value.endpoint !== "string" || !/^\/(receipts|transfers|waste|counts|lots\/[a-f0-9-]+\/quarantine)$/.test(value.endpoint) || !("kind" in value) || typeof value.kind !== "string" || !("fields" in value) || typeof value.fields !== "object" || value.fields === null || !("request_key" in value.fields) || typeof value.fields.request_key !== "string")) throw new Error("Die ausstehende Lagerbuchung konnte nicht sicher gelesen werden. Bitte den Service kontaktieren.");
        pendingRef.current = value as PendingBooking | null;
        setPending(pendingRef.current);
      } catch (cause) { setRecoveryBlocked(true); setError(message(cause)); }
    };
    read();
    const changed = () => {
      const current = auth.getUser();
      const currentKey = current?.sub ? PENDING_PREFIX + encodeURIComponent(JSON.stringify([current.tenant_id, current.sub, venue.id])) : null;
      if (currentKey !== key) { mounted.current = false; pendingRef.current = null; setPending(null); setDialog(null); setTraceLot(null); setData(null); setHistory([]); setError("Bitte erneut persönlich anmelden."); }
    };
    const storage = (event: StorageEvent) => { changed(); if (event.key === key && mounted.current) read(); };
    window.addEventListener(PENDING_CHANGED, read);
    window.addEventListener(AUTH_CHANGED_EVENT, changed);
    window.addEventListener("storage", storage);
    return () => { window.removeEventListener(PENDING_CHANGED, read); window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", storage); };
  }, [venue.id]);

  const reload = useCallback(async () => {
    const snapshot = await inventoryApi<InventorySnapshot>(venue.id, "/snapshot");
    if (mounted.current) setData(snapshot);
  }, [venue.id]);

  const loadHistory = useCallback(async () => {
    const rows = await inventoryApi<StockOperation[]>(venue.id, "/operations?limit=100");
    if (mounted.current) { setHistory(rows); setHasMore(rows.length === 100); }
  }, [venue.id]);

  useEffect(() => {
    mounted.current = true;
    void Promise.all([reload(), loadHistory()]).catch((cause: unknown) => {
      if (mounted.current) setError(message(cause));
    });
    return () => { mounted.current = false; };
  }, [reload, loadHistory]);
  useLive(reload);

  function open(kind: Dialog["kind"], balance?: StockBalance) {
    if (pendingRef.current || recoveryBlocked || inFlight.current) return;
    setError("");
    setNotice("");
    if (balance && ["transfer", "waste", "count", "quarantine"].includes(kind)) {
      setDialog({ kind: kind as "transfer" | "waste" | "count" | "quarantine", key: newRequestId(), balance, lotVersion: data?.lots.find(lot => lot.id === balance.lot_id)?.version ?? 1 });
    } else {
      if (kind === "receipt") setReceiptItem(data?.items[0]?.id ?? "");
      if (kind === "item") setMasterUnit("kg");
      setDialog({ kind: kind as "item" | "owner" | "location" | "receipt", key: newRequestId() });
    }
  }

  async function executeBooking(request: PendingBooking) {
    if (inFlight.current || recoveryBlocked) return;
    const key = currentScope();
    if (!key || key !== scope.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const retry = pendingRef.current !== null;
    try { localStorage.setItem(key, JSON.stringify(request)); }
    catch { setError("Der Browser kann diese Lagerbuchung nicht absichern. Bitte Speicher freigeben und erneut versuchen."); return; }
    pendingRef.current = request;
    setPending(request);
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await inventoryApi(venue.id, request.endpoint, "POST", request.fields);
      if (currentScope() !== key) return;
      localStorage.removeItem(key);
      pendingRef.current = null;
      setPending(null);
      if (!mounted.current) return;
      setDialog(null);
      setNotice("Lagerbuchung gespeichert.");
      try { await Promise.all([reload(), loadHistory()]); }
      catch { setNotice("Lagerbuchung gespeichert. Die Übersicht konnte noch nicht aktualisiert werden."); }
    } catch (cause) {
      if (currentScope() !== key) return;
      if (!retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) {
        localStorage.removeItem(key);
        pendingRef.current = null;
        setPending(null);
      }
      if (mounted.current) setError(message(cause));
    } finally { window.dispatchEvent(new Event(PENDING_CHANGED)); inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) { await executeBooking(pendingRef.current); return; }
    if (!dialog || busy || !data || inFlight.current || recoveryBlocked) return;
    const form = new FormData(event.currentTarget);
    const current = dialog;
    const fields: Record<string, unknown> = {};
    let endpoint = "";
    if (current.kind === "item") {
      endpoint = "/items";
      Object.assign(fields, {
        sku: str(form, "sku"), name: str(form, "name"), unit: str(form, "unit"),
        requires_expiry: form.has("expiry"), minimum_quantity: str(form, "minimum") || "0",
      });
    } else if (current.kind === "owner") {
      endpoint = "/owners";
      Object.assign(fields, { name: str(form, "name"), kind: str(form, "kind"), reference: str(form, "reference") });
    } else if (current.kind === "location") {
      endpoint = "/locations";
      fields.name = str(form, "name");
    } else {
      Object.assign(fields, { request_key: current.key, reason: str(form, "reason") });
      if (current.kind === "receipt") {
        endpoint = "/receipts";
        Object.assign(fields, {
          item_id: str(form, "item"), owner_id: str(form, "owner"), location_id: str(form, "location"),
          lot_code: str(form, "lot"), expires_on: str(form, "expires") || null,
          quantity: str(form, "quantity"), reference: str(form, "reference"), blocked: form.has("blocked"),
        });
      } else if ("balance" in current) {
        const balance = current.balance;
        fields.lot_id = balance.lot_id;
        if (current.kind === "transfer") {
          endpoint = "/transfers";
          Object.assign(fields, { source_location_id: balance.location_id,
            destination_location_id: str(form, "destination"), quantity: str(form, "quantity") });
        } else if (current.kind === "quarantine") {
          endpoint = `/lots/${balance.lot_id}/quarantine`;
          delete fields.lot_id;
          Object.assign(fields, { version: current.lotVersion, blocked: !balance.blocked });
        } else {
          fields.location_id = balance.location_id;
          if (current.kind === "waste") {
            endpoint = "/waste";
            fields.quantity = str(form, "quantity");
          } else {
            endpoint = "/counts";
            Object.assign(fields, { expected_quantity: balance.quantity, counted_quantity: str(form, "counted") });
          }
        }
      }
    }
    if (typeof fields.request_key === "string") { await executeBooking({ endpoint, fields, kind: current.kind }); return; }
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await inventoryApi(venue.id, endpoint, "POST", fields);
      if (!mounted.current) return;
      setDialog(null);
      setNotice(["item", "owner", "location"].includes(current.kind) ? "Stammdaten gespeichert." : "Lagerbuchung gespeichert.");
      await Promise.all([reload(), loadHistory()]);
    } catch (cause) {
      if (mounted.current) setError(message(cause));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function moreHistory() {
    if (!history.length || busy) return;
    setBusy(true);
    try {
      const rows = await inventoryApi<StockOperation[]>(venue.id, `/operations?after=${history[history.length - 1].sequence}&limit=100`);
      setHistory(previous => [...previous, ...rows]);
      setHasMore(rows.length === 100);
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  if (!data) return <section className="fp-panel">{error ? <p className="fp-notice error" role="alert">{error}<button className="fp-button" onClick={() => void reload().catch(cause => setError(message(cause)))}>Erneut laden</button></p> : <Loading />}</section>;

  const items = new Map(data.items.map(row => [row.id, row]));
  const owners = new Map(data.owners.map(row => [row.id, row]));
  const locations = new Map(data.locations.map(row => [row.id, row]));
  const lots = new Map(data.lots.map(row => [row.id, row]));
  const ownTotals = new Map<string, bigint>();
  for (const balance of data.balances) {
    if (owners.get(balance.owner_id)?.kind === "own") ownTotals.set(balance.item_id, (ownTotals.get(balance.item_id) ?? BigInt(0)) + stockMicros(balance.available_quantity));
  }
  const low = data.items.filter(item => (ownTotals.get(item.id) ?? BigInt(0)) < stockMicros(item.minimum_quantity));
  const atRisk = new Set(data.balances.filter(row => stockMicros(row.quantity) > BigInt(0) && (row.expired || row.blocked)).map(row => row.lot_id));
  const visible = data.balances.filter(balance => {
    if (!showZero && stockMicros(balance.quantity) === BigInt(0)) return false;
    const values = [items.get(balance.item_id)?.name, items.get(balance.item_id)?.sku,
      owners.get(balance.owner_id)?.name, locations.get(balance.location_id)?.name, lots.get(balance.lot_id)?.code];
    return values.join(" ").toLocaleLowerCase("de").includes(search.toLocaleLowerCase("de"));
  }).sort((a, b) => (a.expires_on ?? "9999").localeCompare(b.expires_on ?? "9999") || (items.get(a.item_id)?.name ?? "").localeCompare(items.get(b.item_id)?.name ?? ""));
  const canReceive = !!(data.items.length && data.owners.length && data.locations.length) && !pending && !recoveryBlocked;
  const writesLocked = busy || !!pending || recoveryBlocked;
  const selectedBalance = dialog && "balance" in dialog ? dialog.balance : null;
  const selectedItem = selectedBalance ? items.get(selectedBalance.item_id) : items.get(receiptItem);
  const selectedLot = selectedBalance ? lots.get(selectedBalance.lot_id) : null;
  const unit = selectedItem ? stockUnits[selectedItem.unit] : "Einheiten";
  const step = selectedItem?.unit === "piece" ? "1" : "0.000001";
  const titles: Record<Dialog["kind"], string> = {
    item: "Lagerartikel anlegen", owner: "Eigentümer erfassen", location: "Lagerort anlegen",
    receipt: "Wareneingang buchen", transfer: "Ware umlagern", waste: "Schwund erfassen",
    count: "Bestand zählen", quarantine: selectedBalance?.blocked ? "Charge freigeben" : "Charge sperren",
  };

  return <>
    <section className="fp-panel">
      <div className="fp-section-head" style={{ flexWrap: "wrap", gap: 16 }}>
        <div><h2>Was im Lager liegt.</h2><p>Artikel, Chargen und Eigentum an jedem Lagerort.</p></div>
        <div className="fp-inline" style={{ flexWrap: "wrap" }}>
          <button className="fp-icon" aria-label="Lagerbestand aktualisieren" disabled={busy} onClick={() => void Promise.all([reload(), loadHistory()]).catch(cause => setError(message(cause)))}><RefreshCw size={18} /></button>
          <button className="fp-button primary" disabled={!canReceive || busy} onClick={() => open("receipt")}><PackagePlus size={17} /> Wareneingang</button>
        </div>
      </div>
      <div className="fp-inline" style={{ flexWrap: "wrap", marginBottom: 16 }}>
        <Tag>{data.items.length} Lagerartikel</Tag><Tag>{data.locations.length} Lagerorte</Tag>
        <Tag tone={atRisk.size ? "amber" : "green"}>{atRisk.size} Chargen zur Prüfung</Tag>
        <Tag tone={low.length ? "amber" : "green"}>{low.length} unter Mindestbestand</Tag>
      </div>
      {!canReceive && <p className="fp-notice">{manager ? "Lege unter „Artikel & Orte“ zuerst einen Lagerartikel, einen Eigentümer und einen Lagerort an." : "Die Betriebsleitung legt zuerst Artikel, Eigentümer und Lagerorte an."}</p>}
      {low.length > 0 && <p className="fp-notice">Eigener Mindestbestand unterschritten: {low.map(item => item.name).join(", ")}. Reservierte Mengen, gesperrte Chargen und Ware mit überschrittenem MHD zählen dabei nicht zum frei verfügbaren Bestand.</p>}
      <div className="fp-inline" role="group" aria-label="Lageransicht" style={{ flexWrap: "wrap" }}>
        {(["stock", "reservations", "masters", "history"] as const).map(value => <button key={value} className={`fp-button ${tab === value ? "primary" : ""}`} aria-pressed={tab === value} onClick={() => { setTab(value); if (value === "history") void loadHistory().catch(cause => setError(message(cause))); }}>{{ stock: "Bestände", reservations: "Reservierter Bestand", masters: "Artikel & Orte", history: "Buchungsjournal" }[value]}</button>)}
      </div>
    </section>
    {pending && !dialog && <div className="fp-notice" role="status"><span>Eine Lagerbuchung wartet auf Bestätigung: {String(pending.fields.reason ?? "Buchung")}. Der vollständige Vorgang bleibt für die erneute Prüfung gespeichert.</span><button className="fp-button" disabled={busy} onClick={() => void executeBooking(pending)}>Lagerbuchung erneut prüfen</button></div>}
    {notice && <p className="fp-notice" role="status">{notice}</p>}
    {error && !dialog && <p className="fp-notice error" role="alert">{error}</p>}
    {tab === "stock" && <section className="fp-panel">
      <div className="fp-two"><Field label="Artikel, Charge, Ort oder Eigentümer suchen"><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Zum Beispiel Tomaten oder Kühlhaus" /></Field><label className="fp-check"><input type="checkbox" checked={showZero} onChange={event => setShowZero(event.target.checked)} /> Auch leere Bestände zeigen</label></div>
      <div className="fp-table-wrap"><table><thead><tr><th>Artikel / Charge</th><th>Eigentümer</th><th>Lagerort</th><th>Bestand</th><th>MHD</th><th>Aktionen</th></tr></thead><tbody>
        {visible.map(balance => <tr key={`${balance.lot_id}-${balance.location_id}`}>
          <td><strong>{items.get(balance.item_id)?.name}</strong><small>{items.get(balance.item_id)?.sku} · {lots.get(balance.lot_id)?.code}</small>{balance.blocked && <Tag tone="amber">Quarantäne</Tag>}</td>
          <td>{owners.get(balance.owner_id)?.name}<small>{owners.get(balance.owner_id)?.kind === "partner" ? "Partnereigentum" : "Eigener Bestand"}</small></td>
          <td>{locations.get(balance.location_id)?.name}</td>
          <td><strong>{stockQuantity(balance.quantity)} {stockUnits[items.get(balance.item_id)?.unit ?? "piece"]}</strong><small>Frei verfügbar: {stockQuantity(balance.available_quantity)}</small>{stockMicros(balance.reserved_quantity ?? "0") > BigInt(0) && <small>Reserviert: {stockQuantity(balance.reserved_quantity)}</small>}{stockMicros(balance.reservation_shortfall_quantity ?? "0") > BigInt(0) && <Tag tone="amber">Reservierung ungedeckt: {stockQuantity(balance.reservation_shortfall_quantity)}</Tag>}</td>
          <td>{balance.expires_on ? balance.expires_on.split("-").reverse().join(".") : "Ohne MHD"}{balance.expired && <small>MHD überschritten</small>}</td>
          <td><div className="fp-inline" style={{ flexWrap: "wrap" }}>
            <button className="fp-icon" disabled={busy} aria-label={`Charge ${lots.get(balance.lot_id)?.code} rückverfolgen`} onClick={() => setTraceLot(balance.lot_id)}><ScanSearch size={17} /></button>
            <button className="fp-icon" disabled={writesLocked || data.locations.length < 2 || stockMicros(balance.quantity) === BigInt(0)} aria-label={`${items.get(balance.item_id)?.name} umlagern`} onClick={() => open("transfer", balance)}><ArrowRightLeft size={17} /></button>
            <button className="fp-icon" disabled={writesLocked || stockMicros(balance.quantity) === BigInt(0)} aria-label={`Schwund für ${items.get(balance.item_id)?.name}`} onClick={() => open("waste", balance)}><Trash2 size={17} /></button>
            {manager && <button className="fp-icon" disabled={writesLocked} aria-label={`${items.get(balance.item_id)?.name} zählen`} onClick={() => open("count", balance)}><ClipboardCheck size={17} /></button>}
            {(!balance.blocked || manager) && <button className="fp-icon" disabled={writesLocked} aria-label={`Charge ${lots.get(balance.lot_id)?.code} ${balance.blocked ? "freigeben" : "sperren"}`} onClick={() => open("quarantine", balance)}><ShieldAlert size={17} /></button>}
          </div></td>
        </tr>)}
      </tbody></table></div>
      {!visible.length && <Empty title={search ? "Kein passender Bestand" : "Dein Lager ist bereit"}>{search ? "Passe die Suche an oder zeige auch leere Bestände." : "Der erste Wareneingang legt die Charge an und macht den Bestand sichtbar."}</Empty>}
    </section>}
    {tab === "reservations" && <InventoryReservations venue={venue} stock={data} onChange={reload} />}
    {tab === "masters" && <>
      <section className="fp-panel"><div className="fp-section-head"><h2>Lagerartikel</h2>{manager && <button className="fp-button" disabled={writesLocked} onClick={() => open("item")}><Plus size={16} /> Artikel</button>}</div>
        <div className="fp-table-wrap"><table><thead><tr><th>Artikel</th><th>Basiseinheit</th><th>Eigenbestand verfügbar</th><th>Mindestbestand</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.sku}{item.requires_expiry ? " · MHD erforderlich" : ""}</small></td><td>{stockUnits[item.unit]}</td><td>{formatStockMicros(ownTotals.get(item.id) ?? BigInt(0))} {stockUnits[item.unit]}</td><td>{stockQuantity(item.minimum_quantity)} {stockUnits[item.unit]}</td></tr>)}</tbody></table></div>
        {!data.items.length && <Empty title="Zutaten und Handelsware erfassen">Lege hier die Waren an, die du tatsächlich lagerst.</Empty>}
      </section>
      <div className="fp-two"><section className="fp-panel"><div className="fp-section-head"><h2>Eigentümer</h2>{manager && <button className="fp-button" disabled={writesLocked} onClick={() => open("owner")}><Plus size={16} /> Eigentümer</button>}</div>{data.owners.map(owner => <div className="fp-list-row" key={owner.id}><div><strong>{owner.name}</strong><small>{owner.reference}</small></div><Tag>{owner.kind === "partner" ? "Partner" : "Eigener Betrieb"}</Tag></div>)}{!data.owners.length && <Empty title="Wem gehört die Ware?">Erfasse deinen Betrieb und bei Bedarf Partner.</Empty>}</section>
        <section className="fp-panel"><div className="fp-section-head"><h2>Lagerorte</h2>{manager && <button className="fp-button" disabled={writesLocked} onClick={() => open("location")}><Plus size={16} /> Lagerort</button>}</div>{data.locations.map(location => <div className="fp-list-row" key={location.id}><strong>{location.name}</strong></div>)}{!data.locations.length && <Empty title="Wo liegt die Ware?">Zum Beispiel Kühlhaus, Trockenlager oder Bar.</Empty>}</section></div>
    </>}
    {tab === "history" && <section className="fp-panel"><h2>Buchungsjournal</h2><p>Jede Mengenänderung bleibt mit Zeitpunkt, Charge und Begründung erhalten.</p>
      {history.map(operation => <article className="fp-list-row" key={operation.id}><div style={{ minWidth: 0, overflowWrap: "anywhere" }}><strong>{stockOperationNames[operation.kind] ?? operation.kind} · {operation.reason}</strong><small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short", timeZone: venue.timezone }).format(new Date(operation.created_at))} · Buchung {operation.sequence}</small>{operation.movements.map(movement => {
        const lot = lots.get(movement.lot_id); const item = lot ? items.get(lot.item_id) : null;
        return <small key={movement.id}>{stockMicros(movement.quantity) > BigInt(0) ? "+" : ""}{stockQuantity(movement.quantity)} {item ? stockUnits[item.unit] : ""} {item?.name} · {lot?.code} · {locations.get(movement.location_id)?.name}</small>;
      })}{operation.kind === "quarantine" && <small>{operation.details.blocked ? "Charge gesperrt" : "Charge freigegeben"}</small>}{operation.kind === "count" && <small>Gezählt: {String(operation.details.counted_quantity)} · Bestand vorher: {String(operation.details.expected_quantity)}</small>}</div></article>)}
      {!history.length && <Empty title="Noch keine Lagerbuchung">Wareneingänge und folgende Bewegungen erscheinen hier.</Empty>}
      {hasMore && <button className="fp-button" disabled={busy} onClick={() => void moreHistory()}>Weitere Buchungen laden</button>}
    </section>}
    {traceLot && <LotTrace key={traceLot} venue={venue} lotId={traceLot} inventory={data} onClose={() => setTraceLot(null)} onRecalled={() => void Promise.all([reload(), loadHistory()]).catch(cause => setError(message(cause)))} />}
    {dialog && <Modal title={titles[dialog.kind]} onClose={() => { if (!busy) setDialog(null); }}>
      {error && <p className="fp-notice error" role="alert">{error}</p>}
      {pending && <p className="fp-notice" role="status">Die Bestätigung steht aus. Die erneute Prüfung verwendet dieselben Mengen und dieselbe Vorgangs-ID.</p>}
      <form onSubmit={submit}><fieldset className="fp-fieldset" disabled={writesLocked}>
        {dialog.kind === "item" && <><Field label="Lagernummer"><input name="sku" required maxLength={60} pattern="[A-Za-z0-9._-]+" /></Field><Field label="Artikelname"><input name="name" required minLength={2} maxLength={120} /></Field><Field label="Basiseinheit"><select name="unit" value={masterUnit} onChange={event => setMasterUnit(event.target.value)}><option value="kg">Kilogramm</option><option value="l">Liter</option><option value="piece">Stück</option></select></Field><Field label="Mindestbestand"><input name="minimum" type="number" min="0" max="999999999" step={masterUnit === "piece" ? "1" : "0.000001"} defaultValue="0" required /></Field><label className="fp-check"><input name="expiry" type="checkbox" /> MHD beim Wareneingang erforderlich</label></>}
        {dialog.kind === "owner" && <><Field label="Name des Eigentümers"><input name="name" required minLength={2} maxLength={120} /></Field><Field label="Eigentum"><select name="kind"><option value="own">Eigener Betrieb</option><option value="partner">Partner</option></select></Field><Field label="Referenz (optional)"><input name="reference" maxLength={120} /></Field></>}
        {dialog.kind === "location" && <Field label="Name des Lagerorts"><input name="name" required minLength={2} maxLength={120} placeholder="Zum Beispiel Kühlhaus" /></Field>}
        {dialog.kind === "receipt" && <>
          <Field label="Lagerartikel"><select name="item" required value={receiptItem} onChange={event => setReceiptItem(event.target.value)}>{data.items.map(item => <option value={item.id} key={item.id}>{item.name} · {stockUnits[item.unit]}</option>)}</select></Field>
          <Field label="Eigentümer dieser Ware"><select name="owner" required>{data.owners.map(owner => <option value={owner.id} key={owner.id}>{owner.name}{owner.kind === "partner" ? " · Partner" : ""}</option>)}</select></Field>
          <Field label="Lagerort"><select name="location" required>{data.locations.map(location => <option value={location.id} key={location.id}>{location.name}</option>)}</select></Field>
          <div className="fp-two"><Field label="Liefercharge"><input name="lot" required maxLength={100} /></Field><Field label={`Menge in ${unit}`}><input name="quantity" type="number" min={step} max="999999999" step={step} required /></Field><Field label={selectedItem?.requires_expiry ? "MHD" : "MHD (optional)"}><input name="expires" type="date" required={selectedItem?.requires_expiry} /></Field><Field label="Lieferschein / Referenz"><input name="reference" required maxLength={120} /></Field></div>
          <label className="fp-check"><input name="blocked" type="checkbox" /> Charge zunächst in Quarantäne halten</label>
        </>}
        {selectedBalance && <><p><strong>{selectedItem?.name}</strong> · Charge {selectedLot?.code}<br />{locations.get(selectedBalance.location_id)?.name} · {owners.get(selectedBalance.owner_id)?.name}</p><p>Aktueller Bestand: <strong>{stockQuantity(selectedBalance.quantity)} {unit}</strong></p></>}
        {dialog.kind === "transfer" && selectedBalance && <Field label="Zielort"><select name="destination" required>{data.locations.filter(location => location.id !== selectedBalance.location_id).map(location => <option key={location.id} value={location.id}>{location.name}</option>)}</select></Field>}
        {(dialog.kind === "transfer" || dialog.kind === "waste") && selectedBalance && <Field label={`Menge in ${unit}`}><input name="quantity" type="number" min={step} max={selectedBalance.quantity} step={step} required /></Field>}
        {dialog.kind === "count" && <><Field label={`Tatsächlich gezählt in ${unit}`}><input name="counted" type="number" min="0" max="999999999" step={step} required /></Field><p className="fp-description">Die Differenz zum angezeigten Bestand wird als eigene Buchung festgehalten. Bei einer zwischenzeitlichen Bewegung muss der Bestand erneut geprüft werden.</p></>}
        {dialog.kind === "quarantine" && <p className="fp-description">{selectedBalance?.blocked ? "Die Betriebsleitung bestätigt die Prüfung und gibt diese Charge an allen Lagerorten frei. Ein überschrittenes MHD bleibt sichtbar." : "Diese Charge wird an allen Lagerorten als gesperrt geführt. Der physische Bestand bleibt erhalten."}</p>}
        {!["item", "owner", "location"].includes(dialog.kind) && <Field label="Begründung"><textarea name="reason" required minLength={3} maxLength={300} defaultValue={dialog.kind === "receipt" ? "Wareneingang geprüft" : ""} /></Field>}
        </fieldset><button className="fp-button primary wide" disabled={busy || recoveryBlocked}>{busy ? "Wird gespeichert …" : pending ? "Lagerbuchung erneut prüfen" : ["item", "owner", "location"].includes(dialog.kind) ? "Anlegen" : "Buchung bestätigen"}</button>
      </form>
    </Modal>}
  </>;
}
