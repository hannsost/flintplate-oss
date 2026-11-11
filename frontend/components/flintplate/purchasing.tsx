"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Check, ClipboardCheck, FilePlus2, PackagePlus, Plus, RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, money, str, type Venue } from "@/lib/flintplate";
import { formatStockMicros, inventoryApi, stockMicros, stockQuantity, stockUnits, type InventorySnapshot } from "@/lib/flintplate-inventory";
import { inputCents, purchaseStates, purchasingApi, type PurchaseInvoice, type PurchaseLine, type PurchaseOrder, type PurchasingSnapshot, type SupplierProduct } from "@/lib/flintplate-purchasing";
import { Empty, Field, Loading, Modal, Tag, useLive } from "./shared";
import { DeliveryConfirmations } from "./delivery-confirmations";
import type { DeliveryConfirmation } from "@/lib/flintplate-deliveries";
import { SupplierBonuses } from "./supplier-bonuses";
import { ProductConditionFields, readProductConditions } from "./purchase-conditions";
import { PURCHASE_EDITOR_PREFIX, preparePurchaseEditor, readPurchaseEditor, type PurchaseEditorDraft, type PurchasePreparationIntent } from "@/lib/flintplate-purchase-preparation";

interface PurchaseDialog {
  kind: "terms" | "supplier" | "catalog" | "price" | "order" | "receipt" | "invoice" | "orderState" | "invoiceDecision";
  key: string;
  product?: SupplierProduct;
  supplierId?: string;
  order?: PurchaseOrder;
  line?: PurchaseLine;
  invoice?: PurchaseInvoice;
  action?: "ordered" | "cancelled" | "closed" | "approved" | "rejected";
  editor?: PurchaseEditorDraft;
}
interface InvoiceEntry { quantity: string; net: string; tax: string }
interface PendingPurchase { endpoint: string; fields: Record<string, unknown>; kind: string }
const PENDING_PREFIX = "flintplate:purchasing-pending:v1:";
const PENDING_CHANGED = "flintplate-purchasing-pending-changed";

interface PurchasingProps { venue: Venue; preparation?: PurchasePreparationIntent | null; onPrepared?: () => void }
export function PurchasingPanel(props: PurchasingProps) {
  return <PurchasingWorkspace key={props.venue.id} {...props} />;
}

function PurchasingWorkspace({ venue, preparation, onPrepared }: PurchasingProps) {
  const [data, setData] = useState<PurchasingSnapshot | null>(null);
  const [confirmations, setConfirmations] = useState<DeliveryConfirmation[]>([]);
  const [receiptConfirmation, setReceiptConfirmation] = useState("");
  const [stock, setStock] = useState<InventorySnapshot | null>(null);
  const [tab, setTab] = useState<"orders" | "catalog" | "invoices" | "bonuses" | "deliveries">("orders");
  const [dialog, setDialog] = useState<PurchaseDialog | null>(null);
  const [supplierId, setSupplierId] = useState("");
  const [stockItemId, setStockItemId] = useState("");
  const [orderPacks, setOrderPacks] = useState<Record<string, string>>({});
  const [invoiceEntries, setInvoiceEntries] = useState<Record<string, InvoiceEntry>>({});
  const [receiptAccepted, setReceiptAccepted] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingPurchase | null>(null);
  const pendingRef = useRef<PendingPurchase | null>(null);
  const scope = useRef<string | null>(null);
  const inFlight = useRef(false);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editorDraft, setEditorDraft] = useState<PurchaseEditorDraft | null>(null);
  const editorRef = useRef<PurchaseEditorDraft | null>(null);
  const mounted = useRef(true);
  const manager = venue.role === "manager";
  const mutationLocked = busy || !!pending || recoveryBlocked;

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
        if (value !== null && (typeof value !== "object" || !("endpoint" in value) || typeof value.endpoint !== "string" || !/^\/(supplier-terms|orders|invoices|orders\/[a-f0-9-]+\/receipts)$/.test(value.endpoint) || !("kind" in value) || typeof value.kind !== "string" || !("fields" in value) || typeof value.fields !== "object" || value.fields === null || !("request_key" in value.fields) || typeof value.fields.request_key !== "string")) throw new Error("Der ausstehende Einkaufsvorgang konnte nicht sicher gelesen werden. Bitte den Service kontaktieren.");
        pendingRef.current = value as PendingPurchase | null;
        setPending(pendingRef.current);
        const saved = key ? localStorage.getItem(key.replace(PENDING_PREFIX, PURCHASE_EDITOR_PREFIX)) : null;
        editorRef.current = readPurchaseEditor(saved); setEditorDraft(editorRef.current);
      } catch (cause) { setRecoveryBlocked(true); setError(message(cause)); }
    };
    read();
    const changed = () => {
      const current = auth.getUser();
      const currentKey = current?.sub ? PENDING_PREFIX + encodeURIComponent(JSON.stringify([current.tenant_id, current.sub, venue.id])) : null;
      if (currentKey !== key) { mounted.current = false; pendingRef.current = null; editorRef.current = null; setEditorDraft(null); setPending(null); setDialog(null); setData(null); setStock(null); setError("Bitte erneut persönlich anmelden."); }
    };
    const storage = (event: StorageEvent) => { changed(); if ((event.key === key || event.key === key?.replace(PENDING_PREFIX, PURCHASE_EDITOR_PREFIX)) && mounted.current) { read(); setDialog(null); } };
    window.addEventListener(PENDING_CHANGED, read);
    window.addEventListener(AUTH_CHANGED_EVENT, changed);
    window.addEventListener("storage", storage);
    return () => { window.removeEventListener(PENDING_CHANGED, read); window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", storage); };
  }, [venue.id]);

  const reload = useCallback(async () => {
    const [next, inventory, delivery] = await Promise.all([
      purchasingApi<PurchasingSnapshot>(venue.id, "/snapshot"), inventoryApi<InventorySnapshot>(venue.id, "/snapshot"), purchasingApi<DeliveryConfirmation[]>(venue.id, "/delivery-confirmations"),
    ]);
    if (mounted.current) { setData(next); setStock(inventory); setConfirmations(delivery); }
  }, [venue.id]);
  useEffect(() => {
    mounted.current = true;
    void reload().catch(cause => { if (mounted.current) setError(message(cause)); });
    return () => { mounted.current = false; };
  }, [reload]);
  useLive(reload);

  function saveEditor(next: PurchaseEditorDraft | null) {
    const current = currentScope();
    if (!current || current !== scope.current) { setError("Bitte erneut persönlich anmelden."); return false; }
    try {
      const key = current.replace(PENDING_PREFIX, PURCHASE_EDITOR_PREFIX);
      const stored = localStorage.getItem(key);
      if (stored !== (editorRef.current ? JSON.stringify(editorRef.current) : null)) throw new Error("Der Einkaufsentwurf wurde in einem anderen Tab geändert. Bitte die Ansicht neu laden.");
      if (next) localStorage.setItem(key, JSON.stringify(next)); else localStorage.removeItem(key);
      editorRef.current = next; setEditorDraft(next); return true;
    } catch (cause) { setError(message(cause)); return false; }
  }

  function rememberOrder(form: HTMLFormElement) {
    if (dialog?.kind !== "order" || !data || mutationLocked) return false;
    const fields = new FormData(form), supplier = str(fields, "supplier");
    const same = editorRef.current?.supplier_id === supplier;
    const prices = Object.fromEntries(data.catalog.filter(product => product.supplier_id === supplier && product.current_price).map(product => [product.id, product.current_price!.id]));
    return saveEditor({ key: dialog.key, supplier_id: supplier, owner_id: str(fields, "owner"), location_id: str(fields, "location"), expected_on: str(fields, "expected"), reason: str(fields, "reason"), packs: { ...(same ? editorRef.current!.packs : {}), ...Object.fromEntries([...fields.entries()].filter(([key]) => key.startsWith("packs:") && Object.hasOwn(prices, key.slice(6))).map(([key, value]) => [key.slice(6), String(value)])) }, price_ids: same ? editorRef.current!.price_ids : prices, supplier_terms_id: same ? editorRef.current!.supplier_terms_id : data.supplier_terms.find(row => row.supplier_id === supplier && row.effective_on <= data.business_date)?.id ?? null });
  }

  function open(kind: PurchaseDialog["kind"], values: Partial<PurchaseDialog> = {}) {
    if (pendingRef.current || recoveryBlocked || inFlight.current) return;
    if (kind === "order") {
      const editor = values.editor ?? editorRef.current;
      if (editor) { setSupplierId(editor.supplier_id); setOrderPacks(editor.packs); setDialog({ kind, key: editor.key, editor }); setError(""); setNotice(""); return; }
    }
    setDialog({ kind, key: newRequestId(), ...values });
    setError(""); setNotice("");
    setSupplierId(values.supplierId ?? values.product?.supplier_id ?? values.order?.supplier_id ?? data?.suppliers[0]?.id ?? "");
    setStockItemId(stock?.items[0]?.id ?? "");
    setOrderPacks({}); setInvoiceEntries({});
    setReceiptAccepted(values.line?.remaining_quantity ?? ""); setReceiptConfirmation("");
  }

  function adoptPreparation() {
    if (!preparation || mutationLocked || dialog || !data) return;
    try {
      const next = preparePurchaseEditor(preparation, newRequestId());
      if (!saveEditor(next)) return;
      open("order", { editor: next }); onPrepared?.();
    } catch (cause) { setError(message(cause)); }
  }

  async function executePending(request: PendingPurchase) {
    if (inFlight.current || recoveryBlocked) return;
    const key = currentScope();
    if (!key || key !== scope.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const retry = pendingRef.current !== null;
    try {
      const existing = localStorage.getItem(key);
      if (existing && existing !== JSON.stringify(request)) {
        setError("Zuerst den bereits ausstehenden Einkaufsvorgang prüfen.");
        window.dispatchEvent(new Event(PENDING_CHANGED));
        return;
      }
      localStorage.setItem(key, JSON.stringify(request));
    } catch { setError("Der Browser kann diesen Einkaufsvorgang nicht absichern. Bitte Speicher freigeben und erneut versuchen."); return; }
    pendingRef.current = request;
    setPending(request);
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      await purchasingApi(venue.id, request.endpoint, "POST", request.fields);
      if (currentScope() !== key) return;
      localStorage.removeItem(key);
      pendingRef.current = null; setPending(null);
      if (request.kind === "order" && editorRef.current?.key === request.fields.request_key) saveEditor(null);
      if (!mounted.current) return;
      setDialog(null);
      setNotice(request.kind === "receipt" ? "Wareneingang und Lagerbestand gespeichert." : "Einkaufsvorgang gespeichert.");
      try { await reload(); }
      catch { setNotice("Einkaufsvorgang gespeichert. Die Übersicht konnte noch nicht aktualisiert werden."); }
    } catch (cause) {
      if (currentScope() !== key) return;
      if (!retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) {
        localStorage.removeItem(key); pendingRef.current = null; setPending(null);
      }
      if (mounted.current) setError(message(cause));
    } finally { window.dispatchEvent(new Event(PENDING_CHANGED)); inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) { await executePending(pendingRef.current); return; }
    if (!dialog || !data || !stock || busy || inFlight.current || recoveryBlocked) return;
    if (dialog.kind === "order" && !rememberOrder(event.currentTarget)) return;
    const form = new FormData(event.currentTarget);
    let endpoint = "";
    const fields: Record<string, unknown> = {};
    const current = dialog;
    if (current.kind === "terms") {
      endpoint = "/supplier-terms";
      const supplier = data.supplier_terms.filter(row => row.supplier_id === supplierId).sort((left, right) => right.version - left.version)[0];
      Object.assign(fields, { request_key: current.key, reason: str(form, "reason"), supplier_id: supplierId, expected_version: supplier?.version ?? 0, effective_on: str(form, "effective"), rules: { minimum_order_net_cents: inputCents(str(form, "minimum_net")), lead_time_calendar_days: Number(str(form, "lead_days")), delivery_weekdays: form.getAll("delivery_day").map(Number), order_cutoff_local: str(form, "cutoff") || null, excluded_delivery_dates: str(form, "excluded_dates").split(/[\s,;]+/).filter(Boolean) } });
    } else if (current.kind === "supplier") {
      endpoint = "/suppliers";
      Object.assign(fields, { name: str(form, "name"), reference: str(form, "reference"), contact: str(form, "contact") });
    } else if (current.kind === "catalog" || current.kind === "price") {
      try { fields.conditions = readProductConditions(form); } catch (cause) { setError(message(cause)); return; }
      Object.assign(fields, { effective_on: str(form, "effective"), pack_price_cents: inputCents(str(form, "price")), tax_rate_bps: inputCents(str(form, "tax")) });
      if (current.kind === "catalog") {
        endpoint = "/catalog";
        Object.assign(fields, { supplier_id: str(form, "supplier"), item_id: str(form, "item"), supplier_sku: str(form, "sku"), pack_name: str(form, "pack"), pack_quantity: str(form, "quantity") });
      } else {
        endpoint = "/prices";
        Object.assign(fields, { product_id: current.product?.id, expected_version: current.product?.version });
      }
    } else if (current.kind === "order") {
      endpoint = "/orders";
      const saved = editorRef.current;
      if (saved && (data.supplier_terms.find(row => row.supplier_id === supplierId && row.effective_on <= data.business_date)?.id ?? null) !== saved.supplier_terms_id) { setError("Die Lieferbedingungen haben sich geändert. Bitte den aktuellen Stand ausdrücklich übernehmen."); return; }
      const lines = data.catalog.filter(product => product.supplier_id === supplierId && product.current_price && Number(orderPacks[product.id] ?? 0) > 0).map(product => ({ product_id: product.id, price_id: product.current_price!.id, packs: Number(orderPacks[product.id]) }));
      if (Object.entries(orderPacks).some(([id, packs]) => Number(packs) > 0 && !data.catalog.some(product => product.id === id && product.supplier_id === supplierId && product.current_price))) { setError("Der Entwurf enthält nicht mehr bestellbare Positionen. Bitte diese ausdrücklich entfernen."); return; }
      if (!lines.length) { setError("Bitte mindestens ein Gebinde bestellen."); return; }
      if (saved && lines.some(line => saved.price_ids[line.product_id] !== line.price_id)) { setError("Mindestens ein Preisstand hat sich geändert. Bitte die aktuellen Konditionen ausdrücklich übernehmen."); return; }
      const invalid = lines.find(line => { const rules = data.catalog.find(product => product.id === line.product_id)?.current_price?.conditions; return !Number.isInteger(line.packs) || (rules && (line.packs < rules.minimum_paid_packs || line.packs % rules.order_multiple !== 0)); });
      if (invalid) { setError("Bitte Mindestgebinde und Bestellvielfaches der ausgewählten Lieferartikel beachten."); return; }
      Object.assign(fields, { request_key: current.key, reason: str(form, "reason"), supplier_id: supplierId, supplier_terms_id: data.supplier_terms.find(row => row.supplier_id === supplierId && row.effective_on <= data.business_date)?.id ?? null, owner_id: str(form, "owner"), location_id: str(form, "location"), expected_on: str(form, "expected") || null, lines });
    } else if (current.kind === "orderState" && current.order) {
      endpoint = `/orders/${current.order.id}/state`;
      Object.assign(fields, { version: current.order.version, status: current.action, reason: str(form, "reason") });
    } else if (current.kind === "receipt" && current.order && current.line) {
      endpoint = `/orders/${current.order.id}/receipts`;
      Object.assign(fields, {
        request_key: current.key, reason: str(form, "reason"), line_id: current.line.id, confirmation_id: receiptConfirmation && receiptConfirmation !== "unconfirmed" ? receiptConfirmation : null, unconfirmed_delivery_reason: str(form, "unconfirmed_reason"), location_id: str(form, "location"),
        lot_code: str(form, "lot"), expires_on: str(form, "expires") || null, blocked: form.has("blocked"),
        accepted_quantity: str(form, "accepted"), accepted_bonus_quantity: str(form, "accepted_bonus") || "0", rejected_bonus_quantity: str(form, "rejected_bonus") || "0", rejected_quantity: str(form, "rejected") || "0", rejection_reason: str(form, "rejection_reason"), reference: str(form, "reference"),
      });
    } else if (current.kind === "invoice") {
      endpoint = "/invoices";
      const lines = Object.entries(invoiceEntries).filter(([, entry]) => stockMicros(entry.quantity) > BigInt(0)).map(([id, entry]) => ({ purchase_line_id: id, quantity: entry.quantity, net_cents: inputCents(entry.net), tax_rate_bps: inputCents(entry.tax) }));
      if (Object.entries(orderPacks).some(([id, packs]) => Number(packs) > 0 && !data.catalog.some(product => product.id === id && product.supplier_id === supplierId && product.current_price))) { setError("Der Entwurf enthält nicht mehr bestellbare Positionen. Bitte diese ausdrücklich entfernen."); return; }
      if (!lines.length) { setError("Bitte mindestens eine Rechnungsposition auswählen."); return; }
      Object.assign(fields, { request_key: current.key, reason: str(form, "reason"), supplier_id: supplierId, number: str(form, "number"), issued_on: str(form, "issued"), lines });
    } else if (current.kind === "invoiceDecision" && current.invoice) {
      endpoint = `/invoices/${current.invoice.id}/decision`;
      Object.assign(fields, { version: current.invoice.version, status: current.action, reason: str(form, "reason") });
    }
    if (!endpoint) return;
    if (typeof fields.request_key === "string") { await executePending({ endpoint, fields, kind: current.kind }); return; }
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      await purchasingApi(venue.id, endpoint, "POST", fields);
      if (!mounted.current) return;
      setDialog(null);
      setNotice(current.kind === "receipt" ? "Wareneingang und Lagerbestand gespeichert." : current.kind === "invoice" ? "Rechnung erfasst und mit Bestellung und Wareneingang verglichen." : "Einkaufsvorgang gespeichert.");
      await reload();
    } catch (cause) { if (mounted.current) setError(message(cause)); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  if (!data || !stock) return <section className="fp-panel">{error ? <p className="fp-notice error" role="alert">{error}<button className="fp-button" onClick={() => void reload().catch(cause => setError(message(cause)))}>Erneut laden</button></p> : <Loading />}</section>;

  const suppliers = new Map(data.suppliers.map(row => [row.id, row]));
  const items = new Map(stock.items.map(row => [row.id, row]));
  const owners = new Map(stock.owners.map(row => [row.id, row]));
  const locations = new Map(stock.locations.map(row => [row.id, row]));
  const selectableCatalog = data.catalog.filter(product => product.supplier_id === supplierId && product.current_price);
  const invoiceChoices = data.orders.filter(order => order.supplier_id === supplierId && !["draft", "cancelled"].includes(order.status)).flatMap(order => order.lines.map(line => ({ order, line })));
  const quoteProduct = (product: SupplierProduct) => {
    const packs = Number(orderPacks[product.id] ?? 0);
    const price = product.current_price;
    const rules = price?.conditions;
    const applicable = rules?.tiers.filter(row => packs >= row.minimum_paid_packs).at(-1);
    const bonus = rules?.natural_rebate ? Math.floor(packs / rules.natural_rebate.buy_packs) * rules.natural_rebate.free_packs : 0;
    return { packs, bonus, price: applicable?.pack_price_cents ?? price?.pack_price_cents ?? 0 };
  };
  const orderedNet = selectableCatalog.reduce((sum, product) => sum + quoteProduct(product).packs * quoteProduct(product).price, 0);
  const supplierTerms = data.supplier_terms.find(row => row.supplier_id === supplierId && row.effective_on <= data.business_date);
  const minimumShortfall = Math.max(0, (supplierTerms?.rules.minimum_order_net_cents ?? 0) - orderedNet);
  const unavailableProducts = Object.keys(orderPacks).filter(id => Number(orderPacks[id]) > 0 && !selectableCatalog.some(product => product.id === id));
  const changedQuote = !!editorDraft && dialog?.kind === "order" && (editorDraft.supplier_terms_id !== (supplierTerms?.id ?? null) || selectableCatalog.some(product => Number(orderPacks[product.id] ?? 0) > 0 && editorDraft.price_ids[product.id] !== product.current_price?.id));
  const canOrder = data.catalog.some(product => product.current_price) && stock.owners.length > 0 && stock.locations.length > 0;
  const titles: Record<PurchaseDialog["kind"], string> = {
    terms: "Lieferbedingungen erfassen", supplier: "Lieferant erfassen", catalog: "Lieferartikel anlegen", price: "Neuen Preisstand erfassen", order: "Einkaufsbestellung vorbereiten",
    receipt: "Lieferung annehmen", invoice: "Lieferantenrechnung prüfen", orderState: dialog?.action === "ordered" ? "Bestellung freigeben" : dialog?.action === "closed" ? "Restlieferung schließen" : "Bestellung stornieren",
    invoiceDecision: dialog?.action === "approved" ? "Rechnung fachlich freigeben" : "Rechnung zurückweisen",
  };
  const quantityStep = dialog?.line?.unit === "piece" || items.get(stockItemId)?.unit === "piece" ? "1" : "0.000001";
  const openOrders = data.orders.filter(order => ["ordered", "partial"].includes(order.status));
  const differingInvoices = data.invoices.filter(invoice => invoice.status === "draft" && !invoice.check.matched);

  function updateInvoiceEntry(id: string, field: keyof InvoiceEntry, value: string) {
    setInvoiceEntries(previous => ({ ...previous, [id]: { ...previous[id], [field]: value } }));
  }

  return <>
    {manager && preparation && <section className="fp-panel" aria-label="Einkaufsvorschlag übernehmen"><div className="fp-section-head"><div><span className="fp-eyebrow">Aus dem Betriebsüberblick</span><h2>{preparation.item_name} · {preparation.source.supplier_name}</h2><p>{preparation.source.packs} bezahlte + {preparation.source.bonus_packs ?? 0} Gratisgebinde · {preparation.source.net_cents === null ? "Preis prüfen" : `${money(preparation.source.net_cents)} netto`}</p></div><button className="fp-button" onClick={onPrepared}>Vorschlag schließen</button></div><p className="fp-description">Eigentümer und Lagerort im Formular auswählen. Preise und Lieferbedingungen werden mit dem aktuellen Katalog verglichen. Eine Lieferzusage entsteht erst durch einen gesonderten Beleg.</p>{data.orders.some(order => order.supplier_id === preparation.source.supplier_id && order.status === "draft") && <p className="fp-notice">Für diesen Lieferanten bestehen bereits gespeicherte Entwürfe. Prüfe diese unten vor einer zusätzlichen Bestellung.</p>}{editorDraft && <p className="fp-notice">Ein ungesendeter Entwurf für {suppliers.get(editorDraft.supplier_id)?.name ?? "einen Lieferanten"} ist gespeichert. Bei Ersetzen werden dessen Eingaben verworfen.</p>}<div className="fp-inline wrap">{editorDraft && <button className="fp-button" disabled={mutationLocked || !!dialog} onClick={() => open("order")}>Vorhandenen Entwurf fortsetzen</button>}<button className="fp-button primary" disabled={!canOrder || mutationLocked || !!dialog || preparation.source.packs === null} onClick={adoptPreparation}>{editorDraft ? "Eingaben ersetzen und Vorschlag übernehmen" : "Vorschlag in neuen Entwurf übernehmen"}</button></div></section>}
    {manager && editorDraft && !preparation && <section className="fp-panel"><div className="fp-section-head"><div><h2>Ungesendeter Einkaufsentwurf</h2><p>{suppliers.get(editorDraft.supplier_id)?.name} · Eingaben auf diesem Gerät gespeichert.</p></div><div className="fp-inline wrap"><button className="fp-button primary" disabled={mutationLocked || !!dialog} onClick={() => open("order")}>Entwurf fortsetzen</button><button className="fp-button" disabled={mutationLocked || !!dialog} onClick={() => { if (saveEditor(null)) setNotice("Ungesendete Eingaben verworfen."); }}>Eingaben verwerfen</button></div></div></section>}
    <section className="fp-panel">
      <div className="fp-section-head" style={{ flexWrap: "wrap", gap: 16 }}><div><h2>Vom Lieferanten bis ins Lager.</h2><p>Gebinde bestellen, Lieferungen prüfen und Rechnungen abgleichen.</p></div><div className="fp-inline" style={{ flexWrap: "wrap" }}><button className="fp-icon" aria-label="Einkauf aktualisieren" onClick={() => void reload().catch(cause => setError(message(cause)))}><RefreshCw size={18} /></button>{manager && <button className="fp-button primary" disabled={!canOrder || mutationLocked} onClick={() => open("order")}><Plus size={17} /> Bestellung</button>}</div></div>
      <div className="fp-inline" style={{ flexWrap: "wrap", marginBottom: 16 }}><Tag>{data.suppliers.length} Lieferanten</Tag><Tag>{openOrders.length} offene Lieferungen</Tag>{manager && <Tag tone={differingInvoices.length ? "amber" : "green"}>{differingInvoices.length} Rechnungen mit Differenzen</Tag>}</div>
      {!canOrder && <p className="fp-notice">Für den ersten Einkauf brauchst du Lagerartikel, Eigentümer und Lagerorte im Bereich Lager sowie einen Lieferanten mit Gebinde und aktuellem Preis.</p>}
      <div className="fp-inline" role="group" aria-label="Einkaufsansicht" style={{ flexWrap: "wrap" }}>{(["orders", "catalog", "deliveries", ...(manager ? ["invoices", "bonuses"] : [])] as ("orders" | "catalog" | "invoices" | "bonuses" | "deliveries")[]).map(value => <button key={value} className={`fp-button ${tab === value ? "primary" : ""}`} aria-pressed={tab === value} onClick={() => setTab(value)}>{{ orders: "Bestellungen", catalog: "Lieferanten & Katalog", invoices: "Rechnungsprüfung", bonuses: "Lieferantenboni", deliveries: "Lieferzusagen" }[value]}</button>)}</div>
    </section>
    {notice && <p className="fp-notice" role="status">{notice}</p>}{error && !dialog && <p className="fp-notice error" role="alert">{error}</p>}
    {pending && <section className="fp-panel"><p className="fp-notice" role="status">Ein Einkaufsvorgang wartet auf eine eindeutige Bestätigung. Seine ursprünglichen Angaben bleiben bis zum Abgleich erhalten.</p><button className="fp-button primary" disabled={busy || recoveryBlocked} onClick={() => void executePending(pending)}>Ausstehenden Vorgang erneut prüfen</button></section>}
    {tab === "deliveries" && <DeliveryConfirmations venue={venue} purchasing={data} current={confirmations} onChange={reload} />}
    {tab === "bonuses" && manager && <SupplierBonuses venue={venue} suppliers={data.suppliers} invoices={data.invoices} businessDate={data.business_date} />}
    {tab === "orders" && <>
      {!data.orders.length && <section className="fp-panel"><Empty title="Der nächste Einkauf beginnt hier">Bestellungen halten Preis und Gebinde fest. Nach der Freigabe kannst du Lieferungen annehmen.</Empty></section>}
      {data.orders.map(order => <section className="fp-panel" key={order.id}><div className="fp-section-head" style={{ flexWrap: "wrap", gap: 12 }}><div><h2>{order.number} · {suppliers.get(order.supplier_id)?.name}</h2><p>{owners.get(order.owner_id)?.name} · {locations.get(order.location_id)?.name}{order.expected_on ? ` · Erwartet am ${order.expected_on.split("-").reverse().join(".")}` : ""}</p></div><Tag tone={order.status === "received" ? "green" : order.status === "partial" ? "amber" : "neutral"}>{purchaseStates[order.status]}</Tag></div>
        <div className="fp-table-wrap"><table><thead><tr><th>Artikel / Gebinde</th><th>Bestellt</th><th>Angenommen</th><th>Offen</th><th>Netto</th><th>Aktion</th></tr></thead><tbody>{order.lines.map(line => <tr key={line.id}><td><strong>{line.item_name}</strong><small>{line.supplier_sku} · {line.packs} × {line.pack_name} à {stockQuantity(line.pack_quantity)} {stockUnits[line.unit]}</small></td><td>{stockQuantity(line.ordered_quantity)} {stockUnits[line.unit]}<small>Davon {stockQuantity(line.ordered_bonus_quantity)} gratis</small></td><td>{stockQuantity(line.received_quantity)}<small>Davon {stockQuantity(line.received_bonus_quantity)} gratis</small><small>{stockMicros(line.rejected_quantity) > BigInt(0) ? `${stockQuantity(line.rejected_quantity)} abgelehnt` : ""}</small></td><td>{stockQuantity(line.remaining_quantity)} {stockUnits[line.unit]}</td><td>{money(line.net_cents)}</td><td>{["ordered", "partial"].includes(order.status) && stockMicros(line.remaining_quantity) > BigInt(0) && <button className="fp-button" disabled={mutationLocked} onClick={() => open("receipt", { order, line })}><PackagePlus size={16} /> Annehmen</button>}</td></tr>)}</tbody></table></div>
        <div className="fp-total"><span>Netto {money(order.net_cents)} · Steuer {money(order.tax_cents)}</span><strong>{money(order.total_cents)}</strong></div><p className="fp-description">{order.note}</p>
        {order.earliest_delivery_on && <p>Frühester Zugang zum Zeitpunkt des Bestellentwurfs: {order.earliest_delivery_on}</p>}{order.shortfall_to_minimum_net_cents > 0 && <p className="fp-notice">Zum Mindestbestellwert fehlen {money(order.shortfall_to_minimum_net_cents)} netto.</p>}
        {manager && <div className="fp-inline" style={{ flexWrap: "wrap" }}>{order.status === "draft" && <button className="fp-button primary" disabled={mutationLocked || order.shortfall_to_minimum_net_cents > 0} onClick={() => open("orderState", { order, action: "ordered" })}><Check size={16} /> Freigeben</button>}{["draft", "ordered"].includes(order.status) && <button className="fp-button" disabled={mutationLocked} onClick={() => open("orderState", { order, action: "cancelled" })}>Stornieren</button>}{["ordered", "partial"].includes(order.status) && <button className="fp-button" disabled={mutationLocked} onClick={() => open("orderState", { order, action: "closed" })}>Restlieferung schließen</button>}{!["draft", "cancelled"].includes(order.status) && <button className="fp-button" disabled={mutationLocked} onClick={() => open("invoice", { order })}><FilePlus2 size={16} /> Rechnung erfassen</button>}</div>}
        {order.receipts.length > 0 && <details style={{ marginTop: 16 }}><summary>Wareneingänge ({order.receipts.length})</summary>{order.receipts.map(receipt => <div className="fp-list-row" key={receipt.id}><div><strong>{receipt.reference} · Charge {String(receipt.details.lot_code ?? "")}</strong><small>{stockQuantity(receipt.accepted_quantity)} angenommen · {stockQuantity(receipt.rejected_quantity)} abgelehnt{receipt.rejection_reason ? ` · ${receipt.rejection_reason}` : ""}</small></div></div>)}</details>}
      </section>)}
    </>}
    {tab === "catalog" && <>
      <section className="fp-panel"><div className="fp-section-head"><h2>Lieferanten</h2>{manager && <button className="fp-button" disabled={mutationLocked} onClick={() => open("supplier")}><Plus size={16} /> Lieferant</button>}</div>{data.suppliers.map(supplier => <div className="fp-list-row" key={supplier.id}><div><strong>{supplier.name}</strong><small>{[supplier.reference, supplier.contact].filter(Boolean).join(" · ")}</small>{data.supplier_terms.filter(row => row.supplier_id === supplier.id && row.effective_on <= data.business_date).slice(0, 1).map(row => <small key={row.id}>Mindestwarenwert {money(row.rules.minimum_order_net_cents)} netto · Lieferfrist {row.rules.lead_time_calendar_days} Kalendertage · Version {row.version}</small>)}</div>{manager && <button className="fp-button" disabled={mutationLocked} onClick={() => open("terms", { supplierId: supplier.id })}>Lieferbedingungen</button>}</div>)}{!data.suppliers.length && <Empty title="Deine Bezugsquellen erfassen">Name, Kundennummer und Kontakt bleiben direkt beim Lieferanten.</Empty>}</section>
      <section className="fp-panel"><div className="fp-section-head"><h2>Gebinde und Preise</h2>{manager && <button className="fp-button" disabled={!data.suppliers.length || !stock.items.length || mutationLocked} onClick={() => open("catalog")}><Plus size={16} /> Lieferartikel</button>}</div><div className="fp-table-wrap"><table><thead><tr><th>Lieferant / Artikel</th><th>Gebinde</th><th>Aktueller Nettopreis</th><th>Preisstände</th><th>Aktion</th></tr></thead><tbody>{data.catalog.map(product => <tr key={product.id}><td><strong>{items.get(product.item_id)?.name}</strong><small>{suppliers.get(product.supplier_id)?.name} · {product.supplier_sku}</small></td><td>{product.pack_name}<small>{stockQuantity(product.pack_quantity)} {stockUnits[items.get(product.item_id)?.unit ?? "piece"]}</small></td><td>{product.current_price ? money(product.current_price.pack_price_cents) : "Noch kein gültiger Preis"}<small>{product.current_price ? `${product.current_price.tax_rate_bps / 100} % Steuer` : ""}</small></td><td><details><summary>{product.prices.length} Preisstände</summary>{product.prices.map(price => <small key={price.id}>{price.effective_on.split("-").reverse().join(".")} · {money(price.pack_price_cents)} · {price.tax_rate_bps / 100} %</small>)}</details></td><td>{manager && <button className="fp-button" disabled={mutationLocked} onClick={() => open("price", { product })}>Neuer Preis</button>}</td></tr>)}</tbody></table></div>{!data.catalog.length && <Empty title="Wie wird die Ware geliefert?">Zum Beispiel eine Kiste mit 2,5 kg. Im Lager wird dieselbe Ware in kg geführt.</Empty>}</section>
    </>}
    {tab === "invoices" && manager && <>
      <section className="fp-panel"><div className="fp-section-head"><div><h2>Rechnungen nachvollziehbar prüfen.</h2><p>Bestellpreis, angenommene Menge und bereits abgerechnete Ware werden gemeinsam geprüft.</p></div><button className="fp-button" disabled={mutationLocked || !data.orders.some(order => !["draft", "cancelled"].includes(order.status))} onClick={() => open("invoice")}><Plus size={16} /> Rechnung</button></div></section>
      {data.invoices.map(invoice => <section className="fp-panel" key={invoice.id}><div className="fp-section-head"><div><h2>{invoice.number} · {suppliers.get(invoice.supplier_id)?.name}</h2><p>Vom {invoice.issued_on.split("-").reverse().join(".")}</p></div><Tag tone={invoice.status === "approved" ? "green" : !invoice.check.matched ? "amber" : "neutral"}>{invoice.status === "approved" ? "Fachlich freigegeben" : invoice.status === "rejected" ? "Zurückgewiesen" : invoice.check.matched ? "Abgleich stimmt" : "Differenzen prüfen"}</Tag></div>
        {invoice.check.lines.map(line => <div key={line.purchase_line_id} className="fp-list-row"><div><strong>{line.item_name} · {stockQuantity(line.quantity)} {stockUnits[line.unit]} · {money(line.net_cents)} netto</strong><small>Bestellpreis für diese Menge: {money(line.expected_net_cents)} · Kostenpflichtig angenommen: {stockQuantity(line.received_quantity)} · Gratis: {stockQuantity(line.received_bonus_quantity)} · Bisher abgerechnet: {stockQuantity(line.already_invoiced_quantity)}</small>{line.differences.map(difference => <p className="fp-notice error" key={difference}>{difference}</p>)}</div></div>)}
        <div className="fp-total"><span>Netto {money(invoice.check.net_cents)} · Steuer {money(invoice.check.tax_cents)}</span><strong>{money(invoice.check.total_cents)}</strong></div>{invoice.decision_reason && <p>{invoice.decision_reason}</p>}
        {invoice.status === "draft" && <div className="fp-inline" style={{ flexWrap: "wrap" }}><button className="fp-button primary" disabled={!invoice.check.matched || mutationLocked} onClick={() => open("invoiceDecision", { invoice, action: "approved" })}><ClipboardCheck size={16} /> Fachlich freigeben</button><button className="fp-button" disabled={mutationLocked} onClick={() => open("invoiceDecision", { invoice, action: "rejected" })}>Zurückweisen</button></div>}
      </section>)}{!data.invoices.length && <section className="fp-panel"><Empty title="Noch keine Lieferantenrechnung">Erfasse Rechnungspositionen zu deinen freigegebenen Bestellungen.</Empty></section>}
    </>}
    {dialog && <Modal title={titles[dialog.kind]} onClose={() => { if (!busy) setDialog(null); }}>
      {error && <p className="fp-notice error" role="alert">{error}</p>}
      <form onSubmit={submit} onChange={event => { rememberOrder(event.currentTarget); }}>
        <fieldset disabled={busy || !!pending || recoveryBlocked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        {dialog.kind === "supplier" && <><Field label="Lieferantenname"><input name="name" minLength={2} maxLength={120} required /></Field><Field label="Kundennummer / Referenz"><input name="reference" maxLength={120} /></Field><Field label="Kontakt"><input name="contact" maxLength={200} /></Field></>}
        {["terms", "catalog", "order", "invoice"].includes(dialog.kind) && <Field label="Lieferant"><select name="supplier" required value={supplierId} onChange={event => { setSupplierId(event.target.value); setOrderPacks({}); setInvoiceEntries({}); }}>{data.suppliers.map(supplier => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></Field>}
        {dialog.kind === "terms" && <div key={supplierId}>
          <Field label="Lieferbedingungen gültig ab"><input name="effective" type="date" defaultValue={data.business_date} required /></Field>
          <div className="fp-two"><Field label="Mindestbestellwert netto in €"><input name="minimum_net" type="number" min="0" max="10000000" step="0.01" defaultValue={(supplierTerms?.rules.minimum_order_net_cents ?? 0) / 100} required /></Field><Field label="Lieferfrist in Kalendertagen"><input name="lead_days" type="number" min="0" max="365" step="1" defaultValue={supplierTerms?.rules.lead_time_calendar_days ?? 0} required /></Field></div>
          <Field label="Bestellschluss in Betriebszeit (optional)"><input name="cutoff" type="time" defaultValue={supplierTerms?.rules.order_cutoff_local?.slice(0, 5) ?? ""} /></Field>
          <div className="fp-form-box"><p>Erlaubte Liefertage</p>{["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"].map((name, day) => <label key={day} className="fp-check"><input name="delivery_day" type="checkbox" value={day} defaultChecked={supplierTerms?.rules.delivery_weekdays.includes(day) ?? true} /> {name}</label>)}</div>
          <Field label="Ausgeschlossene Liefertage, jeweils JJJJ-MM-TT"><textarea name="excluded_dates" defaultValue={supplierTerms?.rules.excluded_delivery_dates.join("\n") ?? ""} /></Field><p className="fp-description">Die Lieferfrist ist eine Planannahme. Eine tatsächlich bestätigte Lieferantenzusage wird dadurch nicht erzeugt.</p>
        </div>}
        {dialog.kind === "catalog" && <><Field label="Lagerartikel"><select name="item" required value={stockItemId} onChange={event => setStockItemId(event.target.value)}>{stock.items.map(item => <option key={item.id} value={item.id}>{item.name} · {stockUnits[item.unit]}</option>)}</select></Field><Field label="Artikelnummer beim Lieferanten"><input name="sku" maxLength={80} required /></Field><div className="fp-two"><Field label="Gebindename"><input name="pack" maxLength={80} required placeholder="Zum Beispiel Kiste" /></Field><Field label={`Inhalt je Gebinde in ${stockUnits[items.get(stockItemId)?.unit ?? "piece"]}`}><input name="quantity" type="number" min={quantityStep} max="999999999" step={quantityStep} required /></Field></div></>}
        {dialog.kind === "price" && dialog.product && <p>{items.get(dialog.product.item_id)?.name} · {dialog.product.pack_name} mit {stockQuantity(dialog.product.pack_quantity)} {stockUnits[items.get(dialog.product.item_id)?.unit ?? "piece"]}</p>}
        {(dialog.kind === "catalog" || dialog.kind === "price") && <><div className="fp-two"><Field label="Nettopreis je Gebinde in €"><input name="price" type="number" min="0" max="1000000" step="0.01" defaultValue={dialog.product?.current_price ? dialog.product.current_price.pack_price_cents / 100 : undefined} required /></Field><Field label="Steuersatz in %"><input name="tax" type="number" min="0" max="100" step="0.01" defaultValue={dialog.product?.current_price ? dialog.product.current_price.tax_rate_bps / 100 : undefined} required /></Field></div><Field label="Preis gültig ab"><input name="effective" type="date" defaultValue={data.business_date} required /></Field><ProductConditionFields initial={dialog.product?.current_price?.conditions} /></>}
        {dialog.kind === "order" && <>
          <p className="fp-description">Eingaben bleiben bei Tabwechsel und Neuladen erhalten. Abmelden löscht lokale Entwürfe.</p>
          {unavailableProducts.length > 0 && <p className="fp-notice error" role="alert">{unavailableProducts.length} gespeicherte Positionen sind im aktuellen Katalog nicht mehr bestellbar.<button type="button" className="fp-button" onClick={() => { const packs = Object.fromEntries(Object.entries(orderPacks).filter(([id]) => !unavailableProducts.includes(id))); if (editorRef.current && saveEditor({ ...editorRef.current, packs })) setOrderPacks(packs); }}>Nicht bestellbare Positionen entfernen</button></p>}
          {changedQuote && <p className="fp-notice" role="status">Die angezeigten Konditionen weichen vom gespeicherten Entwurf ab. Mengen und aktuellen Preis prüfen.<button type="button" className="fp-button" onClick={() => { if (editorRef.current && saveEditor({ ...editorRef.current, price_ids: Object.fromEntries(selectableCatalog.map(product => [product.id, product.current_price!.id])), supplier_terms_id: supplierTerms?.id ?? null })) setError(""); }}>Aktuelle Konditionen übernehmen</button></p>}
          <Field label="Eigentümer der gelieferten Ware"><select name="owner" defaultValue={dialog.editor?.owner_id ?? stock.owners[0]?.id ?? ""} required><option value="" disabled>Eigentümer auswählen</option>{stock.owners.map(owner => <option key={owner.id} value={owner.id}>{owner.name}</option>)}</select></Field><Field label="Vorgesehener Lagerort"><select name="location" defaultValue={dialog.editor?.location_id ?? stock.locations[0]?.id ?? ""} required><option value="" disabled>Lagerort auswählen</option>{stock.locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}</select></Field><Field label="Erwartete Lieferung (optional)"><input name="expected" type="date" defaultValue={dialog.editor?.expected_on ?? ""} /></Field>
          {selectableCatalog.map(product => <div className="fp-form-box" key={product.id}><Field label={`${items.get(product.item_id)?.name} · Anzahl ${product.pack_name}`}><input name={`packs:${product.id}`} type="number" min="0" max="1000000" step="1" value={orderPacks[product.id] ?? "0"} onChange={event => setOrderPacks(previous => ({ ...previous, [product.id]: event.target.value }))} /></Field><small>Preisstand {product.current_price?.version} · ab {product.current_price?.effective_on.split("-").reverse().join(".")}</small><small>Ab {product.current_price?.conditions.minimum_paid_packs ?? 1} bezahlten Gebinden · Vielfaches von {product.current_price?.conditions.order_multiple ?? 1}</small><small>{stockQuantity(product.pack_quantity)} {stockUnits[items.get(product.item_id)?.unit ?? "piece"]} je Gebinde · {money(quoteProduct(product).price)} netto · {quoteProduct(product).bonus} Gratisgebinde{ /^\d+$/.test(orderPacks[product.id] ?? "0") ? ` · Gesamt ${formatStockMicros(stockMicros(product.pack_quantity) * BigInt(quoteProduct(product).packs + quoteProduct(product).bonus))} ${stockUnits[items.get(product.item_id)?.unit ?? "piece"]}` : ""}</small></div>)}
          {!selectableCatalog.length && <p>Für diesen Lieferanten ist noch kein Gebinde mit gültigem Preis erfasst.</p>}<p><strong>Bestellwert netto: {money(orderedNet)}</strong></p>{minimumShortfall > 0 && <p className="fp-notice">Zum Mindestbestellwert fehlen {money(minimumShortfall)}. Der Entwurf kann gespeichert werden; die Freigabe bleibt gesperrt.</p>}<p className="fp-description">Der Entwurf hält diese Preise fest. Die Freigabe erfolgt danach in der Bestellung; die Übermittlung an den Lieferanten erfolgt außerhalb dieser Ansicht.</p>
        </>}
        {dialog.kind === "orderState" && dialog.order && <><p><strong>{dialog.order.number}</strong> · {suppliers.get(dialog.order.supplier_id)?.name} · {money(dialog.order.total_cents)}</p><p>{dialog.action === "closed" ? "Noch offene Mengen bleiben dokumentiert. Für diese Bestellung werden keine weiteren Lieferungen angenommen." : dialog.action === "ordered" ? "Gebinde, Mengen und Preise sind geprüft; die Bestellung wird für die Lieferannahme freigegeben." : "Der Entwurf beziehungsweise die noch nicht angenommene Bestellung wird storniert."}</p></>}
        {dialog.kind === "receipt" && dialog.order && dialog.line && <>
          <p><strong>{dialog.order.number} · {dialog.line.item_name}</strong><br />Offen: {stockQuantity(dialog.line.remaining_quantity)} {stockUnits[dialog.line.unit]}</p>
          {confirmations.some(row => row.line_id === dialog.line!.id && row.status === "confirmed" && Number(row.remaining_physical_quantity) > 0) && <><Field label="Zuordnung zur offenen Lieferzusage"><select value={receiptConfirmation} onChange={event => setReceiptConfirmation(event.target.value)} required><option value="" disabled>Lieferung ausdrücklich zuordnen</option>{confirmations.filter(row => row.line_id === dialog.line!.id && row.status === "confirmed" && Number(row.remaining_physical_quantity) > 0).map(row => <option key={row.id} value={row.id}>{row.reference} · Version {row.version} · {stockQuantity(row.remaining_physical_quantity)} {stockUnits[dialog.line!.unit]} offen</option>)}<option value="unconfirmed">Andere, nicht zugesagte Lieferung</option></select></Field>{receiptConfirmation === "unconfirmed" && <Field label="Begründung für Lieferung außerhalb der Zusage"><input name="unconfirmed_reason" required minLength={3} maxLength={300} /></Field>}</>}
          <Field label="Lagerort der Annahme"><select name="location" defaultValue={dialog.order.location_id} required>{stock.locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}</select></Field>
          <div className="fp-two"><Field label={`Angenommen in ${stockUnits[dialog.line.unit]}`}><input name="accepted" type="number" min="0" max={dialog.line.remaining_quantity} step={dialog.line.unit === "piece" ? "1" : "0.000001"} value={receiptAccepted} onChange={event => setReceiptAccepted(event.target.value)} required /></Field><Field label={`Abgelehnt in ${stockUnits[dialog.line.unit]}`}><input name="rejected" type="number" min="0" max="999999999" step={dialog.line.unit === "piece" ? "1" : "0.000001"} defaultValue="0" /></Field></div>
          {Number(dialog.line.ordered_bonus_quantity) > 0 && <div className="fp-two"><Field label={`Davon gratis angenommen in ${stockUnits[dialog.line.unit]}`}><input name="accepted_bonus" type="number" min="0" max={Math.min(Number(dialog.line.remaining_bonus_quantity), Number(receiptAccepted || 0))} step={dialog.line.unit === "piece" ? "1" : "0.000001"} defaultValue={dialog.line.remaining_bonus_quantity} required /></Field><Field label={`Davon gratis abgelehnt in ${stockUnits[dialog.line.unit]}`}><input name="rejected_bonus" type="number" min="0" max="999999999" step={dialog.line.unit === "piece" ? "1" : "0.000001"} defaultValue="0" /></Field></div>}
          <Field label="Grund für abgelehnte Ware"><input name="rejection_reason" maxLength={300} placeholder="Zum Beispiel beschädigt oder Temperaturabweichung" /></Field><div className="fp-two"><Field label="Liefercharge"><input name="lot" maxLength={100} required /></Field><Field label="MHD"><input name="expires" type="date" required={Number(receiptAccepted) > 0 && items.get(dialog.line.item_id)?.requires_expiry} /></Field></div><Field label="Lieferschein / Referenz"><input name="reference" maxLength={120} required /></Field><label className="fp-check"><input name="blocked" type="checkbox" /> Angenommene Charge in Quarantäne halten</label>
        </>}
        {dialog.kind === "invoice" && <>
          <div className="fp-two"><Field label="Rechnungsnummer"><input name="number" maxLength={80} required /></Field><Field label="Rechnungsdatum"><input name="issued" type="date" defaultValue={data.business_date} required /></Field></div>
          {invoiceChoices.map(({ order, line }) => {
            const entry = invoiceEntries[line.id];
            return <div className="fp-form-box" key={line.id}><label className="fp-check"><input type="checkbox" checked={!!entry} onChange={event => setInvoiceEntries(previous => {
              const next = { ...previous };
              if (event.target.checked) next[line.id] = { quantity: "", net: "", tax: String(line.tax_rate_bps / 100) };
              else delete next[line.id];
              return next;
            })} /> {order.number} · {line.item_name}</label><small>{stockQuantity(line.billable_received_quantity)} {stockUnits[line.unit]} kostenpflichtig angenommen · {stockQuantity(line.received_bonus_quantity)} gratis · {money(line.pack_price_cents)} netto je {stockQuantity(line.pack_quantity)} {stockUnits[line.unit]}</small>{entry && <div className="fp-two"><Field label={`Berechnete Menge in ${stockUnits[line.unit]}`}><input type="number" min={line.unit === "piece" ? "1" : "0.000001"} max="999999999" step={line.unit === "piece" ? "1" : "0.000001"} value={entry.quantity} onChange={event => updateInvoiceEntry(line.id, "quantity", event.target.value)} required /></Field><Field label="Berechneter Nettobetrag in €"><input type="number" min="0" max="1000000" step="0.01" value={entry.net} onChange={event => updateInvoiceEntry(line.id, "net", event.target.value)} required /></Field><Field label="Steuersatz laut Rechnung in %"><input type="number" min="0" max="100" step="0.01" value={entry.tax} onChange={event => updateInvoiceEntry(line.id, "tax", event.target.value)} required /></Field></div>}</div>;
          })}
          {!invoiceChoices.length && <p>Zu diesem Lieferanten liegt noch keine freigegebene Bestellung vor.</p>}
        </>}
        {dialog.kind === "invoiceDecision" && dialog.invoice && <><p><strong>{dialog.invoice.number}</strong> · {money(dialog.invoice.check.total_cents)}</p><p>{dialog.action === "approved" ? "Die Freigabe hält den geprüften Rechnungsstand fest. Die Rechnung bleibt im Einkauf nachvollziehbar." : "Die zurückgewiesene Rechnung bleibt erhalten. Eine korrigierte Rechnung kann mit derselben Lieferantennummer erneut erfasst werden."}</p></>}
        {!["supplier", "catalog", "price"].includes(dialog.kind) && <Field label="Begründung / Notiz"><textarea name="reason" minLength={3} maxLength={300} required defaultValue={dialog.kind === "receipt" ? "Lieferung geprüft" : dialog.kind === "invoice" ? "Lieferantenrechnung erfasst" : dialog.editor?.reason ?? ""} /></Field>}
        </fieldset>
        <button className="fp-button primary wide" disabled={busy || recoveryBlocked}>{busy ? "Wird gespeichert …" : pending ? "Ausstehenden Vorgang erneut prüfen" : dialog.kind === "invoice" ? "Rechnung erfassen und vergleichen" : "Bestätigen"}</button>
      </form>
    </Modal>}
  </>;
}
