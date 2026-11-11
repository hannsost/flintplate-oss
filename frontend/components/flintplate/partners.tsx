"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, money, str, venueApi, type Draft, type Order, type Venue } from "@/lib/flintplate";
import { inventoryApi, stockQuantity, stockUnits, type InventorySnapshot } from "@/lib/flintplate-inventory";
import { inputCents } from "@/lib/flintplate-purchasing";
import { followingMonth, partnerApi, partnerKinds, type LoanAccount, type PartnerCandidates, type PartnerContract, type PartnerRules, type PartnerSnapshot, type SettlementPreview } from "@/lib/flintplate-partners";
import { Empty, Field, Loading, Modal, Tag, useLive } from "./shared";

type Dialog = { kind: "contract" | "terms" | "stock" | "loan" | "loanEntry" | "settlement"; key: string; contract?: PartnerContract; loan?: LoanAccount; preview?: SettlementPreview };
interface Pending { endpoint: string; payload: Record<string, unknown> }
const PREFIX = "flintplate:partner-pending:v1:";
const CHANGED = "flintplate-partner-pending-changed";
const defaults: PartnerRules = { revenue_basis: "net", share_bps: 0, revenue_threshold_cents: 0, per_sale_cents: 0, fixed_monthly_cents: 0, minimum_monthly_cents: null, loss_responsibility: "partner", loss_per_stock_unit_cents: 0 };

export function PartnersPanel({ venue }: { venue: Venue }) { return <PartnersWorkspace key={venue.id} venue={venue} />; }

function PartnersWorkspace({ venue }: { venue: Venue }) {
  const [data, setData] = useState<PartnerSnapshot | null>(null);
  const [stock, setStock] = useState<InventorySnapshot | null>(null);
  const [menu, setMenu] = useState<Draft[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [orderId, setOrderId] = useState("");
  const [candidates, setCandidates] = useState<PartnerCandidates | null>(null);
  const [tab, setTab] = useState<"contracts" | "sales" | "settlements" | "loans">("contracts");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [contractId, setContractId] = useState("");
  const [loanKind, setLoanKind] = useState("received");
  const [preview, setPreview] = useState<SettlementPreview | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [blocked, setBlocked] = useState(false);
  const inflight = useRef(false);
  const mounted = useRef(true);
  const scope = useRef<string | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  const selectedOrder = useRef("");

  const authScope = () => { const user = auth.getUser(); return user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null; };
  const reload = useCallback(async () => {
    const [next, inventory, drafts, recent] = await Promise.all([partnerApi<PartnerSnapshot>(venue.id, "/snapshot"), inventoryApi<InventorySnapshot>(venue.id, "/snapshot"), venueApi<Draft[]>(venue.id, "/menu"), venueApi<Order[]>(venue.id, "/orders?include_closed=true&limit=100")]);
    if (mounted.current) { setData(next); setStock(inventory); setMenu(drafts); setOrders(current => [...recent, ...current.filter(row => !recent.some(order => order.id === row.id))]); }
    const target = selectedOrder.current;
    if (target) { const ready = await partnerApi<PartnerCandidates>(venue.id, `/orders/${target}/candidates`); if (mounted.current && selectedOrder.current === target) setCandidates(ready); }
  }, [venue.id]);
  useEffect(() => {
    mounted.current = true;
    const user = auth.getUser();
    const key = user?.sub ? PREFIX + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venue.id])) : null;
    scope.current = key;
    const read = () => {
      try {
        const raw = key ? localStorage.getItem(key) : null;
        const value: unknown = raw ? JSON.parse(raw) : null;
        if (value !== null && (typeof value !== "object" || !("endpoint" in value) || typeof value.endpoint !== "string" || !/^\/(contracts|contracts\/[a-f0-9-]+\/terms|sales|refunds|stock|losses|settlements|loan-entries)$/.test(value.endpoint) || !("payload" in value) || !value.payload || typeof value.payload !== "object" || !("request_key" in value.payload) || typeof value.payload.request_key !== "string")) throw new Error("Der gespeicherte Partnerauftrag konnte nicht sicher gelesen werden. Bitte den Service kontaktieren.");
        pendingRef.current = value as Pending | null; setPending(pendingRef.current);
      } catch (cause) { setBlocked(true); setError(message(cause)); }
    };
    const changed = () => { const current = auth.getUser(); const currentKey = current?.sub ? PREFIX + encodeURIComponent(JSON.stringify([current.tenant_id, current.sub, venue.id])) : null; if (key !== currentKey) { mounted.current = false; setBlocked(true); setData(null); setDialog(null); setCandidates(null); setPending(null); pendingRef.current = null; setError("Bitte erneut persönlich anmelden."); } };
    const storage = (event: StorageEvent) => { changed(); if (event.key === key && mounted.current) read(); };
    read(); void reload().catch(cause => { if (mounted.current) setError(message(cause)); });
    window.addEventListener(CHANGED, read); window.addEventListener(AUTH_CHANGED_EVENT, changed); window.addEventListener("storage", storage);
    return () => { mounted.current = false; window.removeEventListener(CHANGED, read); window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", storage); };
  }, [reload, venue.id]);
  useLive(reload);

  async function post(request: Pending) {
    if (inflight.current || blocked) return;
    const key = authScope();
    if (!key || key !== scope.current || !mounted.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const retry = pendingRef.current !== null;
    try {
      const previous = localStorage.getItem(key);
      if (previous && previous !== JSON.stringify(request)) { window.dispatchEvent(new Event(CHANGED)); setError("Zuerst den bereits ausstehenden Partnerauftrag abgleichen."); return; }
      localStorage.setItem(key, JSON.stringify(request));
    } catch { setError("Der Browser kann diese Buchung nicht absichern. Bitte Browserspeicher prüfen."); return; }
    pendingRef.current = request; setPending(request); inflight.current = true; setBusy(true); setError("");
    try {
      await partnerApi(venue.id, request.endpoint, "POST", request.payload);
      if (authScope() !== key || !mounted.current) return;
      localStorage.removeItem(key); pendingRef.current = null; setPending(null); window.dispatchEvent(new Event(CHANGED));
      setDialog(null); setPreview(null); setNotice("Partnerbuchung bestätigt."); await reload();
    } catch (cause) {
      if (!mounted.current || authScope() !== key) return;
      if (!retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) { localStorage.removeItem(key); pendingRef.current = null; setPending(null); window.dispatchEvent(new Event(CHANGED)); }
      setError(message(cause));
    } finally { inflight.current = false; if (mounted.current) setBusy(false); }
  }

  function open(kind: Dialog["kind"], extra: Partial<Dialog> = {}) { if (pendingRef.current || inflight.current || blocked) return; setDialog({ kind, key: newRequestId(), ...extra }); setContractId(extra.contract?.id ?? data?.contracts[0]?.id ?? ""); setLoanKind("received"); setError(""); setNotice(""); }
  async function chooseOrder(id: string) { selectedOrder.current = id; setOrderId(id); setCandidates(null); if (id) try { const value = await partnerApi<PartnerCandidates>(venue.id, `/orders/${id}/candidates`); if (mounted.current && selectedOrder.current === id) setCandidates(value); } catch (cause) { setError(message(cause)); } }
  async function olderOrders() { if (!orders.length) return; try { const older = await venueApi<Order[]>(venue.id, `/orders?include_closed=true&limit=100&before=${orders[orders.length - 1].id}`); setOrders(current => [...current, ...older.filter(order => !current.some(row => row.id === order.id))]); if (!older.length) setNotice("Keine weiteren Bons vorhanden."); } catch (cause) { setError(message(cause)); } }
  function nextPeriod(contract: PartnerContract) { const closed = data?.settlements.filter(row => row.contract_id === contract.id).map(row => row.month).sort() ?? []; return closed.length ? followingMonth(closed[closed.length - 1]) : contract.terms[0].effective_on; }
  async function showPreview(contract: PartnerContract) { try { const value = await partnerApi<SettlementPreview>(venue.id, `/contracts/${contract.id}/settlement-preview/${nextPeriod(contract)}`); setPreview(value); open("settlement", { contract, preview: value }); } catch (cause) { setError(message(cause)); } }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) { await post(pendingRef.current); return; }
    if (!dialog || inflight.current || blocked) return;
    if (!mounted.current || authScope() !== scope.current) { setError("Bitte erneut persönlich anmelden."); return; }
    const form = new FormData(event.currentTarget);
    const base = { request_key: dialog.key, reason: str(form, "reason") };
    let endpoint = ""; let payload: Record<string, unknown> = {};
    if (dialog.kind === "contract" || dialog.kind === "terms") {
      const fixed = str(form, "fixed_monthly");
      const rules: PartnerRules = { revenue_basis: str(form, "revenue_basis") as "net" | "gross", share_bps: inputCents(str(form, "share_percent")), revenue_threshold_cents: inputCents(str(form, "threshold")), per_sale_cents: inputCents(str(form, "per_sale")), fixed_monthly_cents: (fixed.startsWith("-") ? -1 : 1) * inputCents(fixed.replace(/^-/, "")), minimum_monthly_cents: str(form, "minimum") ? inputCents(str(form, "minimum")) : null, loss_responsibility: str(form, "loss_responsibility") as "venue" | "partner", loss_per_stock_unit_cents: inputCents(str(form, "loss_price")) };
      payload = { ...base, effective_on: str(form, "effective_month") + "-01", active: form.get("active") === "on", stock_per_sale: str(form, "stock_per_sale"), rules };
      if (dialog.contract) { endpoint = `/contracts/${dialog.contract.id}/terms`; payload.expected_version = dialog.contract.terms[dialog.contract.terms.length - 1].version; }
      else { endpoint = "/contracts"; payload = { ...payload, name: str(form, "name"), owner_id: str(form, "owner_id"), item_id: str(form, "item_id"), menu_item_id: str(form, "menu_item_id") }; }
    } else if (dialog.kind === "stock") { const [lot, location] = str(form, "balance").split("/"); endpoint = "/stock"; payload = { ...base, contract_id: contractId, lot_id: lot, location_id: location, quantity: str(form, "quantity"), kind: str(form, "stock_kind") }; }
    else if (dialog.kind === "settlement" && dialog.preview) { endpoint = "/settlements"; payload = { ...base, contract_id: dialog.preview.contract_id, month: dialog.preview.month, fingerprint: dialog.preview.fingerprint }; }
    else if (dialog.kind === "loanEntry" && dialog.loan) { const physical = ["received", "returned", "broken"].includes(loanKind); endpoint = "/loan-entries"; payload = { ...base, account_id: dialog.loan.id, kind: loanKind, quantity: physical ? Number(str(form, "quantity")) : 0, amount_cents: physical ? 0 : inputCents(str(form, "amount")), external_reference: physical ? "" : str(form, "external_reference") }; }
    else if (dialog.kind === "loan") {
      inflight.current = true; setBusy(true); setError("");
      try { await partnerApi(venue.id, "/loans", "POST", { owner_id: str(form, "owner_id"), name: str(form, "name"), reference: str(form, "reference"), serialized: form.get("serialized") === "on", deposit_per_unit_cents: inputCents(str(form, "deposit")) }); setDialog(null); await reload(); } catch (cause) { setError(message(cause)); } finally { inflight.current = false; setBusy(false); }
      return;
    }
    if (endpoint) await post({ endpoint, payload });
  }

  if (!data || !stock) return <>{error && <p className="fp-notice error" role="alert">{error}</p>}<Loading /></>;
  const ownerName = (id: string) => stock.owners.find(row => row.id === id)?.name ?? "Partner";
  const itemName = (id: string) => stock.items.find(row => row.id === id)?.name ?? "Lagerartikel";
  const contractName = (id: string) => data.contracts.find(row => row.id === id)?.name ?? "Vertrag";
  const activeContract = data.contracts.find(row => row.id === contractId);
  const rules = dialog?.contract?.terms[dialog.contract.terms.length - 1].rules ?? defaults;
  const locked = busy || !!pending || blocked;
  const month = data.business_date.slice(0, 7);
  const balanceOptions = activeContract ? stock.balances.filter(row => row.owner_id === activeContract.owner_id && row.item_id === activeContract.item_id && Number(row.quantity) > 0) : [];
  return <div className="fp-stack">
    <div className="fp-section-head"><div><h2>Partner & Leihgut</h2><p>Eigentum, Warenbewegung und belegte Abrechnung getrennt führen.</p></div><button className="fp-button" disabled={busy} onClick={() => void reload().catch(cause => setError(message(cause)))}><RefreshCw size={16} /> Aktualisieren</button></div>
    {error && <p className="fp-notice error" role="alert">{error}</p>}{notice && <p className="fp-notice" role="status">{notice}</p>}
    {pending && <section className="fp-panel"><p>Ein Partnerauftrag wartet auf eindeutige Bestätigung. Seine ursprünglichen Angaben bleiben erhalten.</p><button className="fp-button primary" disabled={busy || blocked} onClick={() => void post(pending)}>Ausstehenden Auftrag erneut prüfen</button></section>}
    <div className="fp-tabs" role="tablist" aria-label="Partnerbereiche">{([['contracts', 'Verträge'], ['sales', 'Verkäufe & Rückgaben'], ['settlements', 'Abrechnung'], ['loans', 'Leihgut & Pfand']] as const).map(([key, label]) => <button role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}>{label}</button>)}</div>
    {tab === "contracts" && <><div className="fp-section-head"><p>Vertragsregeln gelten je Menüartikel. Liter oder Kilogramm erlauben genaue Teilmengen pro Verkauf.</p><button className="fp-button primary" disabled={locked || !stock.owners.some(row => row.kind === "partner") || !stock.items.length || !menu.length} onClick={() => open("contract")}><Plus size={16} /> Vertrag anlegen</button></div>{!data.contracts.length ? <Empty title="Noch keine Partnerverträge">Zuerst im Lager Partner-Eigentümer und Lagerartikel anlegen, dann einem Menüartikel zuordnen.</Empty> : data.contracts.map(contract => <section className="fp-panel" key={contract.id}><div className="fp-section-head"><div><h3>{contract.name}</h3><p>{ownerName(contract.owner_id)} · {itemName(contract.item_id)}</p></div><button className="fp-button" disabled={locked} onClick={() => open("terms", { contract })}>Neue Vertragsversion</button></div>{contract.terms.map(terms => <p key={terms.id}><Tag>Version {terms.version} ab {terms.effective_on}</Tag> {terms.active ? `${stockQuantity(terms.stock_per_sale)} ${stockUnits[stock.items.find(item => item.id === contract.item_id)?.unit ?? "piece"]} je Verkauf` : "Vertrag ruht"} · {terms.rules.share_bps / 100}% vom {terms.rules.revenue_basis === "net" ? "Netto" : "Brutto"}umsatz über {money(terms.rules.revenue_threshold_cents)} · {money(terms.rules.per_sale_cents)} je Verkauf · monatlich {money(terms.rules.fixed_monthly_cents)}{terms.rules.minimum_monthly_cents !== null && ` · Garantie ${money(terms.rules.minimum_monthly_cents)}`} · Verlust trägt {terms.rules.loss_responsibility === "venue" ? "der Betrieb" : "der Partner"}</p>)}</section>)}</>}
    {tab === "sales" && <>{data.unassigned_losses.length > 0 && <section className="fp-panel"><h3>Lagerverluste noch einem Vertrag zuordnen</h3><p>Diese Warenmengen wurden bereits entnommen. Die Zuordnung ergänzt ausschließlich die Vertragsabrechnung.</p>{data.unassigned_losses.map(loss => <div key={loss.stock_operation_id}><p>{ownerName(loss.owner_id)} · {itemName(loss.item_id)} · {stockQuantity(loss.quantity)} · {loss.reason}</p>{data.contracts.filter(contract => contract.owner_id === loss.owner_id && contract.item_id === loss.item_id).map(contract => <button className="fp-button" disabled={locked} key={contract.id} onClick={() => void post({ endpoint: "/losses", payload: { request_key: newRequestId(), reason: "Bestehenden Lagerverlust dem Vertrag zuordnen", contract_id: contract.id, stock_operation_id: loss.stock_operation_id } })}>{contract.name}: Verlust übernehmen</button>)}</div>)}</section>}<section className="fp-panel"><div className="fp-section-head"><h3>Bezahlte Verkäufe übernehmen</h3><button className="fp-button" disabled={locked || !data.contracts.length} onClick={() => open("stock")}>Eigentümerrückgabe / Bruch</button></div><Field label="Bon"><select value={orderId} onChange={event => void chooseOrder(event.target.value)}><option value="">Bon wählen</option>{orders.map(order => <option key={order.id} value={order.id}>{order.number} · {new Date(order.created_at).toLocaleDateString("de-DE")} · {money(order.total_cents)}</option>)}</select></Field><button className="fp-button" onClick={() => void olderOrders()}>Ältere Bons laden</button>{candidates && <>{candidates.notes.map(note => <p className="fp-notice" key={note}>{note}</p>)}{!candidates.sales.length && !candidates.refunds.length && <p>Keine weiteren vollständig bezahlten Partnereinheiten oder offenen Geldkorrekturen für diesen Bon.</p>}{candidates.sales.map(candidate => <div className="fp-section-head" key={candidate.line_id}><p>{candidate.name} · {candidate.units.length} Einheiten · {money(candidate.gross_cents)} · {stockQuantity(candidate.stock_quantity)} Lagerverbrauch</p><button className="fp-button primary" disabled={locked} onClick={() => void post({ endpoint: "/sales", payload: { request_key: newRequestId(), reason: "Bezahlte Partnereinheiten geprüft", contract_id: candidate.contract_id, order_id: candidates.order_id, line_id: candidate.line_id, units: candidate.units } })}>Verkauf übernehmen</button></div>)}{candidates.refunds.map(candidate => <div className="fp-section-head" key={candidate.cash_entry_id + candidate.contract_id}><p>{contractName(candidate.contract_id)} · Geldrückzahlung {money(candidate.gross_cents)}</p><button className="fp-button" disabled={locked} onClick={() => void post({ endpoint: "/refunds", payload: { request_key: newRequestId(), reason: "Bestätigte Geldrückzahlung abgleichen", contract_id: candidate.contract_id, cash_entry_id: candidate.cash_entry_id } })}>Abrechnung korrigieren</button></div>)}</>}</section><p>Verkaufsübernahme entnimmt freigegebene Partnerware nach Haltbarkeit. Geldrückzahlungen lagern keine Ware zurück.</p><div className="fp-table-wrap"><table className="fp-table"><thead><tr><th>Vertrag / Vorgang</th><th>Warenmenge</th><th>Umsatz</th><th>Verlustkosten</th><th>Ursprung → Buchung</th></tr></thead><tbody>{data.events.map(event => <tr key={event.id}><td>{contractName(event.contract_id)}<br /><Tag>{partnerKinds[event.kind]}</Tag></td><td>{stockQuantity(event.physical_quantity)}</td><td>{money(event.gross_cents)}</td><td>{money(event.loss_cents)}</td><td>{event.source_month.slice(0, 7)} → {event.posting_month.slice(0, 7)}</td></tr>)}</tbody></table></div><p>Die letzten 500 Partnerpositionen werden hier angezeigt; Abrechnungen berücksichtigen das vollständige Journal.</p></>}
    {tab === "settlements" && <><p>Positive Beträge sind an den Partner zahlbar, negative an den Betrieb. Monatsabrechnungen sind interne Vertragsbelege und keine erzeugten Steuerrechnungen.</p>{data.contracts.map(contract => <section className="fp-panel" key={contract.id}><div className="fp-section-head"><h3>{contract.name}</h3><button className="fp-button primary" disabled={locked} onClick={() => void showPreview(contract)}>Monat {nextPeriod(contract).slice(0, 7)} prüfen</button></div>{data.settlements.filter(row => row.contract_id === contract.id).map(settlement => <details key={settlement.id}><summary>{settlement.month.slice(0, 7)} · {money(settlement.payable_to_partner_cents)} · abgeschlossen</summary><SettlementTable preview={settlement.snapshot} /></details>)}</section>)}</>}
    {tab === "loans" && <><div className="fp-section-head"><p>Leihgut bleibt Eigentum des Partners. Die Pfandforderung ändert sich erst mit einem eigenen Geldbeleg.</p><button className="fp-button primary" disabled={locked || !stock.owners.some(row => row.kind === "partner")} onClick={() => open("loan")}>Leihkonto anlegen</button></div>{!data.loans.length && <Empty title="Noch keine Leihkonten">Kisten und Fässer als Stückkonto, einzelne Geräte mit ihrer Serienreferenz führen.</Empty>}{data.loans.map(loan => <section className="fp-panel" key={loan.id}><div className="fp-section-head"><div><h3>{loan.name}</h3><p>{ownerName(loan.owner_id)} · {loan.reference}{loan.serialized && " · Einzelgerät"}</p></div><button className="fp-button" disabled={locked} onClick={() => open("loanEntry", { loan })}>Bewegung / Pfand buchen</button></div><p>{loan.physical_quantity} vorhanden · {loan.returned_quantity} zurückgegeben · {loan.broken_quantity} verloren · Pfandforderung {money(loan.deposit_claim_cents)} · davon rückzahlbar {money(loan.refundable_deposit_cents)}</p><details><summary>Journal ({loan.entries.length})</summary><ul>{loan.entries.map(entry => <li key={entry.id}>{partnerKinds[entry.kind]} · {entry.quantity ? `${entry.quantity} Stück` : money(entry.amount_cents)} · {entry.reason}{entry.external_reference && ` · ${entry.external_reference}`}</li>)}</ul></details></section>)}</>}
    {dialog && <Modal title={{ contract: "Partnervertrag anlegen", terms: "Vertragsbedingungen versionieren", stock: "Partnerware zurückgeben oder abschreiben", settlement: "Monatsabrechnung prüfen", loan: "Leihkonto anlegen", loanEntry: "Leihgut oder Pfand buchen" }[dialog.kind]} onClose={() => { if (!busy) setDialog(null); }}><form key={dialog.key} onSubmit={submit}><fieldset disabled={locked} style={{ border: 0, margin: 0, padding: 0 }}>
      {(dialog.kind === "contract" || dialog.kind === "terms") && <>{dialog.kind === "contract" && <><Field label="Vertragsname"><input name="name" required minLength={2} maxLength={120} /></Field><Field label="Partner-Eigentümer"><select name="owner_id" required>{stock.owners.filter(row => row.kind === "partner").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field><Field label="Lagerartikel"><select name="item_id" required>{stock.items.map(row => <option key={row.id} value={row.id}>{row.name} · {stockUnits[row.unit]}</option>)}</select></Field><Field label="Menüartikel für direkten Wiederverkauf"><select name="menu_item_id" required>{menu.filter(row => !data.contracts.some(contract => contract.menu_item_id === row.id)).map(row => <option key={row.id} value={row.id}>{row.draft.name}</option>)}</select></Field></>}<Field label="Gültig ab Monat"><input type="month" name="effective_month" required defaultValue={dialog.contract ? followingMonth(dialog.contract.terms[dialog.contract.terms.length - 1].effective_on).slice(0, 7) : month} /></Field><Field label="Lager-Basismenge je Verkauf (z. B. 0,2 Liter je Glas)"><input type="number" name="stock_per_sale" min="0.000001" step="0.000001" required defaultValue={dialog.contract?.terms[dialog.contract.terms.length - 1].stock_per_sale ?? "1"} /></Field><label><input type="checkbox" name="active" defaultChecked /> Vertrag aktiv</label><RulesFields rules={rules} /></>}
      {dialog.kind === "stock" && <><Field label="Vertrag"><select value={contractId} onChange={event => setContractId(event.target.value)} required>{data.contracts.map(contract => <option key={contract.id} value={contract.id}>{contract.name}</option>)}</select></Field><Field label="Vorgang"><select name="stock_kind"><option value="return">Rückgabe an Eigentümer</option><option value="waste">Bruch / Verlust</option></select></Field><Field label="Charge und Lagerort"><select name="balance" required>{balanceOptions.map(row => <option key={row.lot_id + row.location_id} value={row.lot_id + "/" + row.location_id}>{stock.lots.find(lot => lot.id === row.lot_id)?.code} · {stock.locations.find(location => location.id === row.location_id)?.name} · {stockQuantity(row.quantity)}{row.blocked ? " · gesperrt" : ""}</option>)}</select></Field><Field label="Menge in Lager-Basiseinheit"><input name="quantity" type="number" min="0.000001" step="0.000001" required /></Field></>}
      {dialog.kind === "settlement" && preview && <><p>Monat {preview.month.slice(0, 7)} · Betrag {money(preview.payable_to_partner_cents)}</p><SettlementTable preview={preview} />{preview.month.slice(0, 7) >= month && <p className="fp-notice">Dieser laufende Monat kann nach Monatsende abgeschlossen werden.</p>}</>}
      {dialog.kind === "loan" && <><Field label="Partner-Eigentümer"><select name="owner_id">{stock.owners.filter(row => row.kind === "partner").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field><Field label="Bezeichnung"><input name="name" minLength={2} required /></Field><Field label="Kontoreferenz / Seriennummer"><input name="reference" required /></Field><label><input type="checkbox" name="serialized" /> Einzelnes nummeriertes Gerät</label><Field label="Pfand pro Stück in Euro"><input name="deposit" type="number" min="0" step="0.01" defaultValue="0" required /></Field></>}
      {dialog.kind === "loanEntry" && <><Field label="Vorgang"><select value={loanKind} onChange={event => setLoanKind(event.target.value)}>{["received", "returned", "broken", "deposit_paid", "deposit_refunded", "deposit_forfeited"].map(kind => <option key={kind} value={kind}>{partnerKinds[kind]}</option>)}</select></Field>{["received", "returned", "broken"].includes(loanKind) ? <Field label="Stückzahl"><input name="quantity" type="number" min="1" step="1" required /></Field> : <><Field label="Betrag in Euro"><input name="amount" type="number" min="0.01" step="0.01" required /></Field><Field label="Externer Zahlungs- oder Verfallsbeleg"><input name="external_reference" required maxLength={160} /></Field><p>Hier einen bereits vorliegenden externen Beleg erfassen. Es wird keine Zahlung ausgelöst.</p></>}</>}
      {dialog.kind !== "loan" && <Field label="Begründung"><input name="reason" required minLength={3} maxLength={300} defaultValue={dialog.kind === "settlement" ? "Monatsabrechnung geprüft" : ""} /></Field>}
    </fieldset><button className="fp-button primary" type="submit" disabled={busy || blocked || (dialog.kind === "settlement" && !pending && (dialog.preview?.month.slice(0, 7) ?? month) >= month)}>{busy ? "Wird geprüft …" : pending ? "Ursprünglichen Auftrag erneut prüfen" : dialog.kind === "settlement" ? "Monat unveränderlich abschließen" : "Speichern"}</button></form></Modal>}
  </div>;
}

function RulesFields({ rules }: { rules: PartnerRules }) {
  return <><Field label="Umsatzbasis"><select name="revenue_basis" defaultValue={rules.revenue_basis}><option value="net">Netto ohne Umsatzsteuer</option><option value="gross">Brutto inklusive Umsatzsteuer</option></select></Field><Field label="Umsatzanteil in Prozent"><input name="share_percent" type="number" min="0" max="100" step="0.01" defaultValue={rules.share_bps / 100} required /></Field><Field label="Umsatzschwelle je Monat in Euro"><input name="threshold" type="number" min="0" step="0.01" defaultValue={rules.revenue_threshold_cents / 100} required /></Field><Field label="Partnerbetrag je Verkaufseinheit in Euro"><input name="per_sale" type="number" min="0" step="0.01" defaultValue={rules.per_sale_cents / 100} required /></Field><Field label="Fester Monatsbetrag in Euro (negativ = Miete an Betrieb)"><input name="fixed_monthly" type="number" step="0.01" defaultValue={rules.fixed_monthly_cents / 100} required /></Field><Field label="Monatliche Mindestgarantie in Euro (leer = keine)"><input name="minimum" type="number" min="0" step="0.01" defaultValue={rules.minimum_monthly_cents === null ? "" : rules.minimum_monthly_cents / 100} /></Field><Field label="Wer trägt Bruch und Verlust?"><select name="loss_responsibility" defaultValue={rules.loss_responsibility}><option value="partner">Partner trägt eigenen Verlust</option><option value="venue">Betrieb ersetzt Vertragswert</option></select></Field><Field label="Verlustwert je Lager-Basiseinheit in Euro"><input name="loss_price" type="number" min="0" step="0.01" defaultValue={rules.loss_per_stock_unit_cents / 100} required /></Field></>;
}

function SettlementTable({ preview }: { preview: SettlementPreview }) { return <div className="fp-table-wrap"><table className="fp-table"><thead><tr><th>Ursprungsmonat</th><th>Umsatzanteil</th><th>Stückbeträge</th><th>Monatsbetrag</th><th>Garantie</th><th>Verlust</th><th>Bereits abgerechnet</th><th>Jetzt</th></tr></thead><tbody>{preview.components.map(row => <tr key={row.source_month}><td>{row.source_month.slice(0, 7)}</td><td>{money(row.share_cents)}</td><td>{money(row.unit_fees_cents)}</td><td>{money(row.fixed_cents)}</td><td>{money(row.guarantee_topup_cents)}</td><td>{money(row.loss_cents)}</td><td>{money(row.previously_settled_cents)}</td><td>{money(row.delta_cents)}</td></tr>)}</tbody></table></div>; }
