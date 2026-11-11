"use client";
import { newRequestId } from "@/lib/flintplate-uuid";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Info, Minus, Plus, Search, ShoppingBag, Sparkles, Trash2, Undo2, UtensilsCrossed } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { api, labels, message, money, type Item, type Order, type Resource, type SuggestResult } from "@/lib/flintplate";
import { AUTH_CHANGED_EVENT, ORDER_DRAFT_CHANGED_EVENT, emptyOrderDraft, orderDraftKey, orderDraftScope, readOrderDraft, readOrderTarget, writeOrderDraft, type OrderDraft, type OrderTarget, type CartRow, type OrderRequest, type RoundRequest } from "@/lib/flintplate-drafts";
import { cartRowKey, changeRoundQuantity, roundRows } from "@/lib/flintplate-rounds";
import { commitOrderUndo, emptyOrderUndo, orderUndoContent, rebaseOrderUndo, recordOrderUndo, type OrderUndo } from "@/lib/flintplate-order-undo";
import { Empty, Field, Loading, Modal, Tag } from "./shared";
import { DishDetails } from "./nutrition";
import "./order-composer.css";

export interface RoundComposerContext {
  id: string;
  version: number;
  label: string;
  tableId: string | null;
  tabs: { id: string; label: string; version: number; active: boolean }[];
  activeId: string;
  disabled: boolean;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDone: () => Promise<void>;
  onBusyChange: (busy: boolean) => void;
}
interface ComposerProps {
  items: Item[];
  resources?: Resource[];
  endpoint: string;
  onDone?: (order: Order) => void;
  round?: RoundComposerContext;
  guest?: boolean;
  initialTable?: string;
  onTableChange?: (table: string) => void;
  tableOrders?: boolean;
  venueId?: string;
  confirmWarnings?: boolean;
  appendOrder?: Order;
}

export function OrderComposer({ items, resources = [], endpoint, onDone, round, guest = false, initialTable = "", onTableChange, tableOrders = false, venueId = "", confirmWarnings = false, appendOrder }: ComposerProps) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("Alle");
  const [details, setDetails] = useState("");
  const [extra, setExtra] = useState<SuggestResult | null>(null);
  const [draft, setDraft] = useState<OrderDraft | null>(null);
  const current = useRef<OrderDraft | null>(null);
  const scope = useRef<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [saved, setSaved] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const historyRef = useRef(emptyOrderUndo());
  const [history, setHistory] = useState(emptyOrderUndo);
  const [undoNotice, setUndoNotice] = useState("");
  const noteGroup = useRef(0);
  const updateHistory = useCallback((value: OrderUndo) => { historyRef.current = value; setHistory(value); }, []);
  const clearHistory = useCallback(() => { updateHistory(emptyOrderUndo()); setUndoNotice(""); }, [updateHistory]);
  const onRoundBusyChange=round?.onBusyChange;
  useEffect(() => { onRoundBusyChange?.(busy || !!draft?.uncertain); }, [busy, draft?.uncertain, onRoundBusyChange]);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 1000px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const restore = () => {
      clearHistory();
      const nextScope = orderDraftScope(auth.getUser(), endpoint);
      scope.current = nextScope;
      current.current = null;
      setDraft(null);
      setSaved(false);
      setCartOpen(false);
      setDiscardOpen(false);
      setError("");
      setStorageError("");
      if (!nextScope) return;
      try {
        const target: OrderTarget = round?.id ? { visitId: round.id, table: initialTable, fulfillment: "dine_in" } : initialTable
          ? { table: initialTable, fulfillment: "dine_in" }
          : readOrderTarget(nextScope) ?? { table: "", fulfillment: appendOrder?.fulfillment === "takeaway" || guest ? "takeaway" : "dine_in" };
        const restored = readOrderDraft(nextScope, target);
        const value = restored ?? emptyOrderDraft(target);
        current.current = value;
        setDraft(value);
        setSaved(!!restored);
      } catch (e) {
        setStorageError(message(e));
      }
    };
    restore();
    const sync = (event: StorageEvent) => {
      const identity = orderDraftScope(auth.getUser(), endpoint);
      if (identity !== scope.current) { restore(); return; }
      if (!identity || !current.current || (event.key !== null && event.key !== orderDraftKey(identity, current.current))) return;
      clearHistory();
      try {
        const next = readOrderDraft(identity, current.current);
        current.current = next ?? emptyOrderDraft(current.current);
        setDraft(current.current);
        setSaved(!!next);
        setError("Der Entwurf wurde in einem anderen Browser-Tab aktualisiert.");
      } catch (e) { setStorageError(message(e)); }
    };
    const syncLocal = () => {
      if (!scope.current || !current.current) return;
      try {
        const next = readOrderDraft(scope.current, current.current);
        if (!next || next.revision !== current.current.revision) {
          clearHistory();
          current.current = next ?? emptyOrderDraft(current.current);
          setDraft(current.current);
          setSaved(!!next);
        }
      } catch (e) { setStorageError(message(e)); }
    };
    window.addEventListener(ORDER_DRAFT_CHANGED_EVENT, syncLocal);
    window.addEventListener("storage", sync);
    window.addEventListener(AUTH_CHANGED_EVENT, restore);
    return () => {
      window.removeEventListener(ORDER_DRAFT_CHANGED_EVENT, syncLocal);
      window.removeEventListener("storage", sync);
      window.removeEventListener(AUTH_CHANGED_EVENT, restore);
    };
  }, [endpoint, guest, initialTable, appendOrder?.fulfillment, clearHistory, round?.id]);

  useEffect(() => {
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      if (!saved && current.current && (current.current.cart.length > 0 || current.current.note)) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [saved]);

  const chosen = draft?.cart.map(row => row.item.id).join(",") ?? "";
  useEffect(() => {
    let active = true;
    if (!chosen) { setExtra(null); return; }
    api<SuggestResult>(endpoint.replace(/\/(?:orders(?:\/[^/]+\/append)?|service-visits\/[^/]+\/rounds)$/, "/suggestions"), "POST", { item_ids: [...new Set(chosen.split(","))], limit: 3 })
      .then(result => { if (active) setExtra(result); })
      .catch(() => { if (active) setExtra(null); });
    return () => { active = false; };
  }, [chosen, endpoint]);

  // Persist from event handlers, before navigation or any network request. An
  // effect-only save could lose the last keystroke when this tab is unmounted.
  function persist(next: OrderDraft, expected = current.current): boolean {
    const owner = scope.current;
    if (!owner || orderDraftScope(auth.getUser(), endpoint) !== owner) {
      clearHistory();
      current.current = null;
      setDraft(null);
      setError("Die Anmeldung hat sich geändert. Bitte erneut anmelden.");
      return false;
    }
    const previousRevision = next.revision;
    try {
      const stored = readOrderDraft(owner, next);
      if (stored && expected && orderDraftKey(owner, expected) === orderDraftKey(owner, next) && stored.revision !== expected.revision) {
        clearHistory();
        current.current = stored;
        setDraft(stored);
        setError("Dieser Entwurf wurde in einem anderen Tab geändert. Bitte die aktuelle Auswahl prüfen.");
        return false;
      }
      next = { ...next, revision: newRequestId() };
      writeOrderDraft(owner, next, mounted.current);
      updateHistory(rebaseOrderUndo(historyRef.current, orderDraftKey(owner, next), expected?.revision ?? null, next.revision));
      current.current = next;
      setDraft(next);
      setStorageError("");
      setSaved(true);
      return true;
    } catch {
      clearHistory();
      next = { ...next, revision: previousRevision };
      current.current = next;
      setDraft(next);
      setSaved(false);
      setStorageError("Der Browser kann den Entwurf gerade nicht speichern. Bitte diesen Tab offen lassen und Browserspeicher freigeben. Es wurde nichts neu gesendet.");
      return false;
    }
  }

  function edit(change: Partial<OrderDraft>, label = "Auswahl geändert", group: string | null = null) {
    const value = current.current;
    if (!value || inFlight.current || busy || value.uncertain || round?.disabled) return;
    setError("");
    setUndoNotice("");
    const previousHistory = historyRef.current;
    if (persist({ ...value, ...change, pending: null, warning: "", requestKey: newRequestId() }) && scope.current && current.current) {
      updateHistory(recordOrderUndo(previousHistory, orderDraftKey(scope.current, value), value, current.current, label, group));
    }
  }

  function undo() {
    const value = current.current, owner = scope.current;
    if (!value || !owner || inFlight.current || busy || value.uncertain || round?.disabled) return;
    if (orderDraftScope(auth.getUser(), endpoint) !== owner) { clearHistory(); return; }
    try {
      const stored = readOrderDraft(owner, value), key = orderDraftKey(owner, value), previous = historyRef.current;
      const restored = orderUndoContent(previous, key, value, stored?.revision ?? null);
      if (!restored) {
        clearHistory();
        if (!stored || stored.revision !== value.revision) {
          current.current = stored ?? emptyOrderDraft(value); setDraft(current.current); setSaved(!!stored);
          setError("Dieser Entwurf wurde in einem anderen Tab geändert. Rückgängig wurde verworfen; bitte die aktuelle Auswahl prüfen.");
        }
        return;
      }
      if (persist({ ...value, ...restored, pending: null, warning: "", requestKey: newRequestId() }) && current.current) {
        updateHistory(commitOrderUndo(previous, key, value.revision, current.current.revision));
        setError(""); setDiscardOpen(false); setUndoNotice(`${previous.steps.at(-1)?.label ?? "Änderung"} rückgängig gemacht.`);
      }
    } catch (cause) { clearHistory(); setStorageError(message(cause)); }
  }

  function update(item: Item, delta: number, row?: CartRow) {
    const value = current.current;
    if (!value) return;
    if (round) {
      if (delta > 0 && !round.tabs.some(tab => tab.id === (row?.guestTabId ?? round.activeId) && tab.active)) return;
      const cart = row ? value.cart.map(entry => cartRowKey(entry) === cartRowKey(row) ? { ...entry, quantity: Math.min(99, entry.quantity + delta) } : entry).filter(entry => entry.quantity > 0) : changeRoundQuantity(value.cart, item, round.activeId, delta, newRequestId());
      edit({ cart }, `${item.name}: Menge geändert`);
      return;
    }
    const old = value.cart.find(row => row.item.id === item.id);
    const cart = old
      ? value.cart.map(row => row.item.id === item.id ? { ...row, quantity: Math.min(99, row.quantity + delta) } : row).filter(row => row.quantity > 0)
      : delta > 0 ? [...value.cart, { item, quantity: 1 }] : value.cart;
    edit({ cart }, old ? (old.quantity + delta <= 0 ? `${item.name} entfernt` : `Menge von ${item.name} geändert`) : `${item.name} hinzugefügt`);
  }

  function selectTarget(target: OrderTarget) {
    if (busy || !current.current || !scope.current) return;
    if (!persist(current.current)) return;
    clearHistory();
    try {
      const value = readOrderDraft(scope.current, target) ?? emptyOrderDraft(target);
      if (persist(value, null)) {
        setDiscardOpen(false);
        setError("");
        onTableChange?.(target.fulfillment === "dine_in" ? target.table : "");
      }
    } catch (e) { setStorageError(message(e)); }
  }

  async function send(acceptWarnings = false) {
    let value = current.current;
    if (!value || !value.cart.length || inFlight.current) return;
    const owner = scope.current;
    if (!owner || orderDraftScope(auth.getUser(), endpoint) !== owner) return;
    if (guest && value.fulfillment === "dine_in" && !value.table) return;
    if (round && (round.disabled || (!value.uncertain && value.cart.some(row => !round.tabs.some(tab => tab.id === row.guestTabId && tab.active))))) return;
    const retry = value.uncertain;
    const orderNote = value.note;
    const payload: OrderRequest | RoundRequest = value.pending ?? (round ? {
      request_key: value.requestKey,
      visit_version: round.version,
      tab_versions: [...new Set(value.cart.map(row => row.guestTabId))].map(id => ({ guest_tab_id: id!, version: round.tabs.find(tab => tab.id === id)!.version })),
      fulfillment: value.fulfillment,
      note: value.note,
      rows: roundRows(value.cart),
    } : {
      request_key: value.requestKey,
      ...(appendOrder ? { version: appendOrder.version } : {}),
      table_id: value.fulfillment === "dine_in" ? value.table || null : null,
      fulfillment: value.fulfillment,
      guests: 1,
      note: value.note,
      lines: value.cart.map(({ item, quantity, course }) => ({ item_id: item.id, menu_version: item.version, quantity, course: course ?? 1, note: appendOrder ? orderNote : "" })),
    });
    if (acceptWarnings) payload.accept_warnings = true;
    if (!persist({ ...value, pending: payload, uncertain: true, warning: "" })) return;
    value = current.current!;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      let order: Order | null = null;
      if (round) await api<unknown>(endpoint, "POST", payload);
      else order = await api<Order>(endpoint, "POST", payload);
      // A late response must never recreate private data after logout, nor clear
      // a different table opened while this component was unmounted.
      if (orderDraftScope(auth.getUser(), endpoint) !== owner) return;
      const latest = readOrderDraft(owner, value);
      if (latest?.requestKey === value.requestKey) {
        clearHistory();
        const cleared = emptyOrderDraft(value);
        writeOrderDraft(owner, cleared, false);
        if (scope.current === owner && current.current?.requestKey === value.requestKey) {
          current.current = cleared;
          setDraft(cleared);
          setSaved(true);
          setCartOpen(false);
        }
      }
      window.dispatchEvent(new Event(ORDER_DRAFT_CHANGED_EVENT));
      if (mounted.current) { if (round) await round.onDone(); else if (order) onDone?.(order); }
    } catch (e) {
      if (orderDraftScope(auth.getUser(), endpoint) !== owner) return;
      const text = message(e);
      const warning = !retry && confirmWarnings && e instanceof ApiError && e.status === 409 && text.startsWith("Bitte bestätigen");
      if (warning) {
        persist({ ...value, uncertain: false, warning: text.replace("Bitte bestätigen: ", "") }, value);
      } else {
        // After an ambiguous result, even a later 4xx must not silently unlock
        // the payload: the first request may already have created the order.
        const uncertain = retry || !(e instanceof ApiError) || e.status >= 500 || e.status === 408;
        persist({ ...value, uncertain, pending: uncertain ? payload : null, requestKey: uncertain ? value.requestKey : newRequestId() }, value);
        setError(text);
      }
    } finally {
      window.dispatchEvent(new Event(ORDER_DRAFT_CHANGED_EVENT));
      inFlight.current = false;
      setBusy(false);
    }
  }

  if (!draft) return storageError || error
    ? <p className="fp-notice error" role="alert">{storageError || error}</p>
    : <Loading />;

  const { cart, note, table, fulfillment, uncertain, warning } = draft;
  const locked = busy || uncertain || !!round?.disabled;
  const categories = ["Alle", ...new Set(items.map(item => item.category))];
  const filtered = items.filter(item => (category === "Alle" || item.category === category) && `${item.name} ${item.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const count = cart.reduce((sum, row) => sum + row.quantity, 0);
  const total = cart.reduce((sum, row) => sum + row.quantity * (row.item.price_cents + (fulfillment === "takeaway" && row.item.takeaway_packaging ? row.item.takeaway_packaging.price_cents + row.item.takeaway_packaging.deposit_cents : 0)), 0);
  const changedMenu = !uncertain && cart.some(row => items.find(item => item.id === row.item.id)?.version !== row.item.version);
  const unavailable = !uncertain && cart.some(row => !items.find(item => item.id === row.item.id)?.available);
  const targetLabel = round ? `${round.label} · ${fulfillment === "takeaway" ? "To go" : resources.find(resource => resource.id === round.tableId)?.name ?? "Ohne Tisch"}` : fulfillment === "takeaway" ? "Abholung · To go" : resources.find(resource => resource.id === table)?.name ?? "Ohne Tischzuordnung";
  const sendLabel = busy ? "Wird gesendet …" : uncertain ? "Bestellung erneut prüfen" : round ? "Runde senden" : guest ? (fulfillment === "dine_in" ? "An den Tisch bestellen" : "Zur Abholung bestellen") : appendOrder ? `Auf ${appendOrder.number} nachbestellen` : "An Küche & Bar senden";
  const invalidGuest = !!round && !uncertain && cart.some(row => !round.tabs.some(tab => tab.id === row.guestTabId && tab.active));
  const canSend = !!cart.length && !busy && !round?.disabled && !invalidGuest && !changedMenu && !unavailable && !(guest && fulfillment === "dine_in" && !table);

  const renderRow = (row: CartRow) => <div className="fp-cart-line" key={cartRowKey(row)}>
    <div><strong>{row.item.name}</strong><small>{money(row.item.price_cents)} / Stück</small>{!guest && <select className="fp-course-select" aria-label={`Gang für ${row.item.name}`} disabled={locked} value={row.course ?? 1} onChange={event => edit({ cart: cart.map(entry => cartRowKey(entry) === cartRowKey(row) ? { ...entry, course: Number(event.target.value) } : entry) }, `Gang für ${row.item.name} geändert`)}>{Array.from({ length: 12 }, (_, index) => <option key={index + 1} value={index + 1}>Gang {index + 1}</option>)}</select>}{round && <><select aria-label={`Gast für ${row.item.name}`} value={row.guestTabId} disabled={locked} onChange={event => edit({ cart: cart.map(entry => cartRowKey(entry) === cartRowKey(row) ? { ...entry, guestTabId: event.target.value } : entry) }, `${row.item.name}: Gast geändert`)}>{round.tabs.map(tab => <option key={tab.id} value={tab.id} disabled={!tab.active}>{tab.label}{!tab.active ? " · geschlossen" : ""}</option>)}</select><input aria-label={`Notiz für ${row.item.name}`} placeholder="Hinweis zu dieser Position" maxLength={300} disabled={locked} value={row.note ?? ""} onFocus={() => { noteGroup.current++; }} onBlur={() => { noteGroup.current++; }} onChange={event => edit({ cart: cart.map(entry => cartRowKey(entry) === cartRowKey(row) ? { ...entry, note: event.target.value } : entry) }, `${row.item.name}: Notiz geändert`, `${cartRowKey(row)}:${noteGroup.current}`)} /></>}{!items.find(item => item.id === row.item.id)?.available && <small>Aktuell nicht verfügbar</small>}</div>
    <div className="fp-quantity"><button disabled={locked} aria-label={`${row.item.name} weniger`} onClick={() => update(row.item, -1, row)}><Minus size={16} /></button><span>{row.quantity}</span><button disabled={locked || row.quantity >= 99} aria-label={`${row.item.name} mehr`} onClick={() => update(row.item, 1, row)}><Plus size={16} /></button></div>
  </div>;

  const summary = <>
    <div className="fp-cart-context"><Tag tone="green">{targetLabel}</Tag><span aria-live="polite">{count} Artikel</span></div>
    <div className="fp-order-undo"><button className="fp-button" disabled={locked || !history.steps.length} onClick={undo}><Undo2 size={17} /> Rückgängig</button><small>{history.steps.at(-1)?.label ?? "Noch keine lokale Änderung"}</small></div>
    {undoNotice && <p className="fp-description" role="status">{undoNotice}</p>}
    {cart.length === 0 ? <Empty title="Platz für etwas Gutes">Wähle etwas aus der Karte.</Empty> : <div className="fp-cart-lines">{round ? [...new Set(cart.map(row => row.guestTabId))].map(id => <section className="fp-round-cart-group" aria-label={round.tabs.find(tab => tab.id === id)?.label ?? "Gastzuordnung fehlt"} key={id}><h3>{round.tabs.find(tab => tab.id === id)?.label ?? "Gastzuordnung fehlt"}</h3>{cart.filter(row => row.guestTabId === id).map(renderRow)}</section>) : cart.map(renderRow)}</div>}
    {invalidGuest && <p className="fp-notice error" role="alert">Ein Gast dieser Runde ist nicht mehr aktiv. Bitte die betroffenen Positionen einem aktiven Gast zuordnen.</p>}
    <Field label={round ? "Notiz für diese Runde" : appendOrder ? "Hinweis zur Nachbestellung" : "Hinweis zur Bestellung"}><textarea placeholder="Zum Beispiel ohne Zwiebeln …" maxLength={appendOrder ? 300 : 500} disabled={locked} value={note} onFocus={() => { noteGroup.current++; }} onBlur={() => { noteGroup.current++; }} onChange={event => edit({ note: event.target.value }, "Notiz geändert", `note:${noteGroup.current}`)} /></Field>
    {(cart.length > 0 || note) && <div className="fp-draft-state"><small><Check size={14} aria-hidden="true" />{saved ? "Entwurf auf diesem Gerät gespeichert" : "Entwurf noch nicht gesichert"}</small><button className="fp-text-button" disabled={locked} onClick={() => setDiscardOpen(true)}><Trash2 size={15} /> Entwurf verwerfen</button></div>}
    {discardOpen && <div className="fp-tip-box" role="group" aria-label="Entwurf verwerfen"><strong>Entwurf verwerfen?</strong><p>Die ungesendete Auswahl und Notiz für {targetLabel} werden geleert. Solange du hier bleibst, kannst du das rückgängig machen.</p><div className="fp-inline wrap"><button className="fp-button" onClick={() => setDiscardOpen(false)}>Entwurf behalten</button><button className="fp-button danger" disabled={locked} onClick={() => { edit({ cart: [], note: "" }, "Entwurf geleert"); setDiscardOpen(false); }}>Entwurf leeren</button></div></div>}
    {changedMenu && <div className="fp-notice error" role="alert"><span>Die Karte wurde seit deiner Auswahl geändert. Bitte Preise und Verfügbarkeit prüfen.</span><button className="fp-button" onClick={() => edit({ cart: cart.map(row => ({ ...row, item: items.find(item => item.id === row.item.id) ?? row.item })) }, "Kartenstand übernommen")}>Aktuelle Karte übernehmen</button></div>}
    {unavailable && <p className="fp-notice error">Bitte nicht verfügbare Artikel aus der Auswahl entfernen.</p>}
    {!!extra?.suggestions.length && !uncertain && <div className="fp-suggest"><span className="fp-eyebrow"><Sparkles size={14} /> Passt dazu</span>{extra.suggestions.map(row => {
      const item = items.find(entry => entry.id === row.item_id);
      return <button key={row.item_id} className="fp-suggest-row" disabled={!item?.available || locked} onClick={() => { if (item) update(item, 1); }}><span><strong>{row.name}</strong><small>{row.reason}</small></span><b>{money(row.price_cents)}</b></button>;
    })}<small>{extra.basis === "gemeinsame Bestellungen" ? "Aus früheren Bestellungen dieses Betriebs." : "Noch wenig Historie, deshalb die meistbestellten Artikel."}</small></div>}
    {warning && <div className="fp-tip-box" role="alert"><strong>Bitte kurz prüfen</strong><p>{warning}</p><small>Ein Hinweis aus deinen hinterlegten Merkmalen. Du entscheidest.</small><div className="fp-inline"><button className="fp-button" onClick={() => edit({ warning: "" })}>Zur Auswahl zurück</button><button className="fp-button primary" disabled={busy} onClick={() => void send(true)}>Trotzdem bestellen</button></div></div>}
    {uncertain && <div className="fp-notice error" role="status"><span>Die Bestätigung steht noch aus. Bitte diese Bestellung erneut prüfen. Auswahl und Vorgangs-ID bleiben dafür erhalten – auch nach dem Neuladen.</span></div>}
    {error && <p className="fp-notice error" role="alert">{error}</p>}
    {storageError && <p className="fp-notice error" role="alert">{storageError}</p>}
    <div className="fp-cart-checkout"><div className="fp-total"><span>Gesamt inkl. MwSt.</span><strong>{money(total)}</strong></div>{fulfillment === "takeaway" && <small>Inklusive ausgewiesener Verpackung und Pfand.</small>}<button className="fp-button primary wide" disabled={!canSend || !!warning} onClick={() => void send()}>{sendLabel}<ArrowRight size={18} /></button></div>
    <small className="fp-draft-privacy">Private Entwürfe werden beim Abmelden von diesem Gerät gelöscht.</small>
  </>;

  return <div className="fp-order-layout" data-round={round ? "true" : undefined}>
    {details && venueId && <DishDetails venueId={venueId} itemId={details} onClose={() => setDetails("")} />}
    <section className="fp-order-menu" aria-label="Bestellkarte">
      {mobile && !cartOpen && storageError && <p className="fp-notice error" role="alert">{storageError}</p>}
      {round && <div className="fp-round-guests"><div className="fp-inline wrap"><strong>Neue Artikel für {round.tabs.find(tab => tab.id === round.activeId)?.label ?? "Gast wählen"}</strong><div className="fp-segment">{(["dine_in", "takeaway"] as const).map(mode => <button key={mode} disabled={locked} aria-pressed={fulfillment === mode} className={fulfillment === mode ? "active" : ""} onClick={() => { if (fulfillment !== mode) { clearHistory(); persist({ ...draft, fulfillment: mode, pending: null, requestKey: newRequestId() }); } }}>{mode === "dine_in" ? "Vor Ort" : "To go"}</button>)}</div></div><div className="fp-guest-chips" aria-label="Gäste dieser Runde">{round.tabs.filter(tab => tab.active).map(tab => <button className={`fp-button ${round.activeId === tab.id ? "primary" : ""}`} aria-label={tab.label} aria-pressed={round.activeId === tab.id} key={tab.id} disabled={locked} onClick={() => round.onSelect(tab.id)}>{tab.label}<small>{cart.filter(row => row.guestTabId === tab.id).reduce((sum, row) => sum + row.quantity, 0)} Artikel</small></button>)}<button className="fp-button" disabled={locked} onClick={round.onAdd}><Plus size={17} /> Gast hinzufügen</button></div></div>}
      {!round && !appendOrder && (!guest || tableOrders) && <div className="fp-order-context"><div className="fp-segment"><button disabled={busy} aria-pressed={fulfillment === "dine_in"} className={fulfillment === "dine_in" ? "active" : ""} onClick={() => { if (fulfillment !== "dine_in") selectTarget({ table: initialTable, fulfillment: "dine_in" }); }}><UtensilsCrossed size={17} /> Vor Ort</button><button disabled={busy} aria-pressed={fulfillment === "takeaway"} className={fulfillment === "takeaway" ? "active" : ""} onClick={() => { if (fulfillment !== "takeaway") selectTarget({ table: "", fulfillment: "takeaway" }); }}><ShoppingBag size={17} /> To go</button></div>{fulfillment === "dine_in" && <Field label={guest ? "Dein Tisch" : "Tisch oder Aktivität"}><select required={guest} disabled={busy} value={table} onChange={event => selectTarget({ table: event.target.value, fulfillment: "dine_in" })}><option value="">{guest ? "Bitte Tisch wählen" : "Ohne Zuordnung"}</option>{resources.filter(resource => !guest || resource.kind === "table").map(resource => <option key={resource.id} value={resource.id}>{resource.name}{guest ? "" : ` · ${labels[resource.kind] ?? resource.kind}`}</option>)}</select></Field>}<small>Jeder Tisch und To go haben einen eigenen Entwurf.</small></div>}
      <div className="fp-search"><Search size={18} /><input aria-label="Karte durchsuchen" placeholder="Gericht, Getränk oder Artikel suchen …" value={search} onChange={event => setSearch(event.target.value)} /></div>
      <div className="fp-tabs" aria-label="Kategorien">{categories.map(value => <button key={value} aria-pressed={category === value} className={category === value ? "active" : ""} onClick={() => setCategory(value)}>{value}</button>)}</div>
      <div className="fp-menu-grid">{filtered.map(item => <article className="fp-item" key={item.id}><div className={`fp-item-art ${item.station === "bar" ? "drink" : "food"}`}><span aria-hidden="true">{item.station === "bar" ? "◒" : "◉"}</span><span className="fp-art-leaf" aria-hidden="true" /><Tag>{item.category}</Tag></div><div className="fp-item-body"><h3>{item.name}</h3><p>{item.description}</p>{item.allergens.length > 0 && <small>Allergene: {item.allergens.join(", ")}</small>}{fulfillment === "takeaway" && item.takeaway_packaging && <small>{item.takeaway_packaging.name}: {money(item.takeaway_packaging.price_cents)} · Pfand {money(item.takeaway_packaging.deposit_cents)}</small>}<div className="fp-item-bottom"><strong>{money(item.price_cents)}</strong>{!guest && venueId && <button className="fp-icon small" aria-label={`Zutaten von ${item.name}`} onClick={() => setDetails(item.id)}><Info size={19} /></button>}<button className="fp-add" disabled={!item.available || locked} aria-label={`${item.name} hinzufügen`} onClick={() => update(item, 1)}>{item.available ? <Plus size={21} /> : "Aus"}</button></div></div></article>)}</div>
      {filtered.length === 0 && <Empty title={items.length ? "Nichts Passendes gefunden" : "Die Karte ist noch leer"}>{items.length ? "Probiere einen anderen Suchbegriff oder eine andere Kategorie." : "Veröffentlichte Artikel erscheinen hier automatisch."}</Empty>}
    </section>
    {!mobile && <aside className="fp-cart" aria-label="Warenkorb"><div className="fp-section-head"><h2>{guest ? "Deine Bestellung" : "Bestellung"}</h2><ShoppingBag size={20} /></div>{summary}</aside>}
    {mobile && <><div className="fp-mobile-cart-bar">{!cartOpen && <div className="fp-order-undo-quick"><button className="fp-button" disabled={locked || !history.steps.length} onClick={undo}><Undo2 size={17} /> Rückgängig</button>{undoNotice ? <small role="status">Letzte Änderung rückgängig gemacht.</small> : <small>Lokaler Entwurf</small>}</div>}<button className="fp-cart-trigger" aria-haspopup="dialog" aria-expanded={cartOpen} onClick={() => setCartOpen(true)}><ShoppingBag size={22} /><span><strong>Warenkorb öffnen · {count}</strong><small>{uncertain ? "Bestätigung ausstehend" : targetLabel}</small></span><b aria-live="polite">{money(total)}</b><ArrowRight size={20} /></button></div>{cartOpen && <Modal title={guest ? "Deine Bestellung" : "Bestellung"} onClose={() => setCartOpen(false)}>{summary}</Modal>}</>}

  </div>;
}
