"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Banknote, Check, Minus, Plus, RefreshCw } from "lucide-react";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { useCashRecovery } from "@/lib/flintplate-cash-recovery";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { api, date, labels, message, money, str, time, venueApi, type Member, type Venue } from "@/lib/flintplate";
import { guestTabLabel, visitLabel, type GuestTab, type OrderServiceContext, type ServicePage, type ServiceVisit } from "@/lib/flintplate-visits";
import { euroCents, euroInput, groupPaymentUnits, planMatchesPayment, paymentUnitKey, selectedUnitAmounts, type EqualPlan, type PayerTip, type PaymentBalance, type PaymentGroup, type PaymentQuote, type PaymentSelection, type UnitAmount } from "@/lib/flintplate-payments";
import { Empty, Field, Loading, Modal, Tag } from "./shared";
import "./visit-payments.css";

const PATHS = /^\/(?:payment-groups\/cash|equal-split-plans(?:\/[^/]+\/actions)?|payer-tips\/[^/]+\/returns)$/;
const principal = () => { const user = auth.getUser(); return user?.sub ? JSON.stringify([user.tenant_id, user.sub]) : null; };
const planKey = (venueId: string, visitId: string) => `flintplate:split-context:v1:${encodeURIComponent(principal() ?? "")}:${venueId}:${visitId}`;
const navigationKey = (venueId: string) => `flintplate:payment-context:v1:${encodeURIComponent(principal() ?? "")}:${venueId}`;
type Mode = "all" | "guests" | "units" | "equal" | "amount" | "tip_only";
type Session = { id: string; register_id: string; operator_id: string; status: string };
const planStatus = { open: "Offen", paid: "Bezahlt", stale: "Auswahl verändert", abandoned: "Aufteilung beendet", superseded: "Durch neue Aufteilung ersetzt" };

async function readPlanSource(venueId: string, value: EqualPlan) {
  const contexts = value.source_order_ids.length ? await venueApi<OrderServiceContext[]>(venueId, `/order-service-contexts?${value.source_order_ids.map(orderId => `order_id=${orderId}`).join("&")}`) : [];
  const visitIds = [...new Set([...(value.source_scope.visit_id ? [value.source_scope.visit_id] : []), ...contexts.map(context => context.visit_id)])];
  const [visits, balance] = await Promise.all([
    Promise.all(visitIds.map(visitId => venueApi<ServiceVisit>(venueId, `/service-visits/${visitId}`))),
    venueApi<PaymentBalance>(venueId, "/payment-groups/balance", "POST", { scope: { order_ids: value.source_order_ids }, limit: 50 }),
  ]);
  return { visits, balance };
}


export function VisitPayments({ venue, initialVisitId = "", initialGuestTabId = "", onManage, onOrder }: { venue: Venue; initialVisitId?: string; initialGuestTabId?: string; onManage: () => void; onOrder: (orderId: string) => void }) {
  return <PaymentsView key={`${venue.id}:${initialVisitId}:${initialGuestTabId}`} venue={venue} initialVisitId={initialVisitId} initialGuestTabId={initialGuestTabId} onManage={onManage} onOrder={onOrder} />;
}
function PaymentsView({ venue, initialVisitId, initialGuestTabId, onManage, onOrder }: Required<Parameters<typeof VisitPayments>[0]>) {
  const [visits, setVisits] = useState<ServicePage<ServiceVisit>>({ items: [], next_before: null, has_more: false });
  const [visit, setVisit] = useState<ServiceVisit | null>(null);
  const [visitId, setVisitId] = useState(initialVisitId);
  const visitRef = useRef(initialVisitId);
  const [balance, setBalance] = useState<PaymentBalance | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [registers, setRegisters] = useState<{ id: string; name: string }[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [userId, setUserId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [mode, setMode] = useState<Mode>(initialGuestTabId ? "guests" : "all");
  const [guests, setGuests] = useState<string[]>(initialGuestTabId ? [initialGuestTabId] : []);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [amount, setAmount] = useState("");
  const [tip, setTip] = useState("0");
  const [payer, setPayer] = useState(initialGuestTabId);
  const [payerLabel, setPayerLabel] = useState("");
  const [recipient, setRecipient] = useState("");
  const [received, setReceived] = useState("");
  const [quote, setQuote] = useState<{ key: string; input: PaymentSelection; value: PaymentQuote } | null>(null);
  const [quoteError, setQuoteError] = useState("");
  const [quoting, setQuoting] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [plan, setPlan] = useState<EqualPlan | null>(null);
  const planRef = useRef<EqualPlan | null>(null);
  const [parts, setParts] = useState<string[]>([]);
  const [combineParts,setCombineParts]=useState(false);
  const [participants, setParticipants] = useState<{ payer_tab_id: string | null; label: string }[]>([{ payer_tab_id: null, label: "Zahler 1" }, { payer_tab_id: null, label: "Zahler 2" }]);
  const [planBase, setPlanBase] = useState<UnitAmount[] | null>(null);
  const [replaceReason, setReplaceReason] = useState("");
  const [replacement, setReplacement] = useState<EqualPlan | null>(null);
  const [planContext, setPlanContext] = useState("");
  const [otherVisits, setOtherVisits] = useState<ServiceVisit[]>([]);
  const othersRef = useRef<ServiceVisit[]>([]);
  const [otherBalances, setOtherBalances] = useState<Record<string, PaymentBalance>>({});
  const [addingVisit, setAddingVisit] = useState(false);
  const [otherId, setOtherId] = useState("");
  const [abandon, setAbandon] = useState(false);
  const [plans, setPlans] = useState<EqualPlan[]>([]);
  const [groups, setGroups] = useState<PaymentGroup[]>([]);
  const [tips, setTips] = useState<PayerTip[]>([]);
  const [moreGroups, setMoreGroups] = useState(false);
  const [morePlans, setMorePlans] = useState(false);
  const [moreTips, setMoreTips] = useState(false);
  const [last, setLast] = useState<PaymentGroup | null>(null);
  const [returnTip, setReturnTip] = useState<PayerTip | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const live = useRef(false), owner = useRef<string | null>(null), generation = useRef(0);
  function rememberNavigation(id: string) { try { localStorage.setItem(navigationKey(venue.id), id); } catch { /* Financial commands have their own mandatory persistence. */ } }
  const choosePlan = useCallback((next: EqualPlan | null, remember = true) => {
    if (!live.current || owner.current !== principal()) return;
    planRef.current = next; setPlan(next);
    const nextPart=next?.status === "open"?next.parts.find(part=>part.remaining_cents>0):undefined;
    setParts(nextPart?[nextPart.id]:[]);
    if(next){setPayer(nextPart?.payer_tab_id??"");setPayerLabel(nextPart?.label??"");}
    if (remember && visitRef.current) { try { if (next) localStorage.setItem(planKey(venue.id, visitRef.current), next.id); else localStorage.removeItem(planKey(venue.id, visitRef.current)); } catch { /* The plan itself remains on the server. */ } }
  }, [venue.id]);
  const showPlanSource = useCallback((value: EqualPlan, source: Awaited<ReturnType<typeof readPlanSource>>) => {
    if (!live.current || owner.current !== principal()) return;
    const first = source.visits[0] ?? null;
    visitRef.current = first?.id ?? ""; setVisitId(first?.id ?? ""); setVisit(first);
    try { localStorage.setItem(navigationKey(venue.id), first?.id ?? ""); } catch { /* Optional navigation only. */ }
    othersRef.current = source.visits.slice(1); setOtherVisits(source.visits.slice(1)); setOtherBalances({}); setBalance(source.balance);
    setPlanContext(source.visits.length ? `Aufteilung aus ${source.visits.map(visitLabel).join(" + ")} · ${value.source_order_ids.length} Originalbons` : `Aufteilung aus ${value.source_order_ids.length} Originalbons ohne Besuchszuordnung`);
    choosePlan(value); setMode("equal");
  }, [choosePlan, venue.id]);
  const load = useCallback(async () => {
    const scope = principal(), id = visitRef.current, version = ++generation.current;
    if (!scope || scope !== owner.current) return;
    setLoading(true);
    try {
      const [nextSessions, nextRegisters, me, nextMembers, nextVisits, nextVisit, nextBalance, nextPlans, nextGroups, nextTips] = await Promise.all([
        venueApi<Session[]>(venue.id, "/cash/sessions"), venueApi<{ id: string; name: string }[]>(venue.id, "/cash/registers"), api<{ id: string }>("/users/me"), venueApi<Member[]>(venue.id, "/members"),
        venueApi<ServicePage<ServiceVisit>>(venue.id, "/service-visits?active=false&limit=50"), id ? venueApi<ServiceVisit>(venue.id, `/service-visits/${id}`) : Promise.resolve(null),
        id ? venueApi<PaymentBalance>(venue.id, "/payment-groups/balance", "POST", { scope: { visit_id: id }, limit: 50 }) : Promise.resolve(null),
        venueApi<EqualPlan[]>(venue.id, "/equal-split-plans?limit=50"), venueApi<PaymentGroup[]>(venue.id, "/payment-groups?limit=50"), venueApi<PayerTip[]>(venue.id, "/payer-tips?limit=50"),
      ]);
      if (!live.current || scope !== principal() || version !== generation.current) return;
      setSessions(nextSessions); setRegisters(nextRegisters); setUserId(me.id); setMembers(nextMembers); setVisits(nextVisits); setVisit(nextVisit); setBalance(nextBalance);
      setSessionId(current => nextSessions.some(value => value.id === current && value.status === "open" && value.operator_id === me.id) ? current : nextSessions.find(value => value.status === "open" && value.operator_id === me.id)?.id ?? "");
      setPlans(nextPlans); setGroups(nextGroups); setTips(nextTips); setMorePlans(nextPlans.length === 50); setMoreGroups(nextGroups.length === 50); setMoreTips(nextTips.length === 50); setError("");
      let remembered = planRef.current?.id ?? "";
      if (!remembered && id) { try { remembered = localStorage.getItem(planKey(venue.id, id)) ?? ""; } catch { /* Server list still available. */ } }
      if (remembered) {
        const value = await venueApi<EqualPlan>(venue.id, `/equal-split-plans/${remembered}`);
        const source = await readPlanSource(venue.id, value);
        if (!live.current || scope !== principal() || version !== generation.current) return;
        showPlanSource(value, source);
      }
      const foreign = await Promise.all(othersRef.current.filter(row => row.id !== id).map(async row => [row.id, await venueApi<PaymentBalance>(venue.id, "/payment-groups/balance", "POST", { scope: { visit_id: row.id }, limit: 50 })] as const));
      if (live.current && scope === principal() && version === generation.current) setOtherBalances(Object.fromEntries(foreign));
    } finally { if (live.current && scope === principal() && version === generation.current) setLoading(false); }
  }, [venue.id, showPlanSource]);
  const afterCommit = async (result: unknown) => {
    await load();
    if (!live.current || owner.current !== principal()) return;
    if (result && typeof result === "object" && "part_payments" in result) { setLast(result as PaymentGroup); setTip("0"); setReceived(""); setChosen({}); setGuests([]); setParts([]); setQuote(null); }
    if (result && typeof result === "object" && "parts" in result) { choosePlan(result as EqualPlan); setMode("equal"); setPlanBase(null); setReplacement(null); setReplaceReason(""); }
    setAbandon(false); setReturnTip(null); setRefresh(value => value + 1);
  };
  const mutation = useVenueMutation(venue.id, "flintplate:payment-group-pending:v1:", PATHS, afterCommit);
  const legacyRecovery=useCashRecovery(venue.id);
  const locked = legacyRecovery.legacy || legacyRecovery.unavailable || loading || mutation.busy || !!mutation.pending || mutation.blocked || !mutation.ready;
  useEffect(() => {
    live.current = true; owner.current = principal();
    const changed = () => { if (owner.current !== principal()) { generation.current++; setVisit(null); setBalance(null); setVisits({ items: [], has_more: false, next_before: null }); setQuote(null); setGroups([]); setPlans([]); setTips([]); setLast(null); setError("Bitte erneut persönlich anmelden."); } };
    window.addEventListener(AUTH_CHANGED_EVENT, changed); window.addEventListener("storage", changed);
    async function restore() {
      let id = initialVisitId;
      if (!id) { try { id = localStorage.getItem(navigationKey(venue.id)) ?? ""; } catch { /* Optional navigation preference. */ } }
      const scope = principal();
      let recovered: { quote?: PaymentSelection; selection?: PaymentSelection; session_id?: string; received_cents?: number } | undefined;
      try {
        const key = `flintplate:payment-group-pending:v1:${encodeURIComponent(JSON.stringify([auth.getUser()?.tenant_id, auth.getUser()?.sub, venue.id]))}`;
        const pending = JSON.parse(localStorage.getItem(key) ?? "null") as { payload?: typeof recovered } | null;
        recovered = pending?.payload;
        const input = pending?.payload?.quote ?? pending?.payload?.selection;
        let sourceScope = input?.scope;
        if (input?.mode === "parts") {
          let before = "", found: EqualPlan | undefined;
          const cursors = new Set<string>();
          do {
            const page = await venueApi<EqualPlan[]>(venue.id, `/equal-split-plans?limit=50${before ? `&before_id=${before}` : ""}`);
            if (!live.current || scope !== principal()) return;
            found = page.find(value => planMatchesPayment(input, value));
            if (found || page.length < 50) break;
            before = page.at(-1)!.id;
            if (cursors.has(before)) throw new Error("Der Verlauf der ausstehenden Aufteilung konnte nicht vollständig gelesen werden.");
            cursors.add(before);
          } while (!found);
          if (!found) throw new Error("Die ausstehenden Zahleranteile konnten keinem gespeicherten Plan zugeordnet werden. Nur den unveränderten Vorgang erneut prüfen.");
          choosePlan(found, false);
          sourceScope = { order_ids: found.source_order_ids };
        }
        if (sourceScope?.visit_id) id = sourceScope.visit_id;
        else if (sourceScope?.order_ids?.length) {
          const contexts = await venueApi<OrderServiceContext[]>(venue.id, `/order-service-contexts?${sourceScope.order_ids.map(orderId => `order_id=${orderId}`).join("&")}`);
          if (!live.current || scope !== principal()) return;
          const found = await Promise.all([...new Set(contexts.map(context => context.visit_id))].map(visitId => venueApi<ServiceVisit>(venue.id, `/service-visits/${visitId}`)));
          if (!live.current || scope !== principal()) return;
          id = found[0]?.id ?? ""; othersRef.current = found.slice(1); setOtherVisits(found.slice(1));
        }
        else if (sourceScope?.guest_tab_ids?.length || input?.payer_tab_id) {
          const ids = sourceScope?.guest_tab_ids?.length ? sourceScope.guest_tab_ids : [input!.payer_tab_id!];
          const tabs = await Promise.all(ids.map(tabId => venueApi<GuestTab>(venue.id, `/guest-tabs/${tabId}`)));
          if (!live.current || scope !== principal()) return;
          const found = await Promise.all([...new Set(tabs.map(tab => tab.visit_id))].map(visitId => venueApi<ServiceVisit>(venue.id, `/service-visits/${visitId}`)));
          if (!live.current || scope !== principal()) return;
          id = found[0]?.id ?? ""; othersRef.current = found.slice(1); setOtherVisits(found.slice(1));
        }
      } catch (cause) {
        if (live.current && scope === principal()) { visitRef.current = ""; setVisitId(""); setError(`Besuchsbezug noch ungeklärt: ${message(cause)}`); setLoading(false); }
        return; // The exact pending command remains visible and retryable independently.
      }
      if (!live.current || scope !== principal()) return;
      visitRef.current = id; setVisitId(id); if(id){try{localStorage.setItem(navigationKey(venue.id),id);}catch{/* Optional context; pending payload remains authoritative. */}} await load();
      const input = recovered?.quote ?? recovered?.selection;
      if (input && live.current && scope === principal()) {
        setMode(input.mode === "parts" ? "equal" : input.scope.guest_tab_ids?.length ? "guests" : input.mode === "all" && recovered?.selection ? "equal" : input.mode);
        setParts(input.part_ids); setCombineParts(input.part_ids.length > 1); setGuests(input.scope.guest_tab_ids ?? []);
        setChosen(Object.fromEntries(input.units.map(unit => [paymentUnitKey(unit), unit.amount_cents === undefined ? "" : euroInput(unit.amount_cents)])));
        setTip(euroInput(input.new_tip_cents)); setPayer(input.payer_tab_id ?? ""); setPayerLabel(input.payer_label); setRecipient(input.recipient_id ?? "");
        if (input.amount_cents !== null) setAmount(euroInput(input.amount_cents));
        if (recovered?.session_id) setSessionId(recovered.session_id);
        if (recovered?.received_cents !== undefined) setReceived(euroInput(recovered.received_cents));
      }
    }
    void restore().catch(cause => { if (live.current && owner.current === principal()) setError(message(cause)); });
    return () => { live.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, changed); window.removeEventListener("storage", changed); };
  }, [load, initialVisitId, venue.id, choosePlan]);

  const selection = useMemo((): { input: PaymentSelection | null; problem: string } => {
    try {
      const newTip = mode === "equal" && !plan ? 0 : euroCents(tip, 100000);
      if (newTip === null) return { input: null, problem: "Bitte einen Trinkgeldbetrag mit höchstens zwei Nachkommastellen eingeben." };
      const payerTab = [visit, ...otherVisits].flatMap(value => value?.tabs ?? []).find(tab => tab.id === payer);
      const input: PaymentSelection = { scope: {}, mode: "all", units: [], part_ids: [], amount_cents: null, new_tip_cents: newTip, payer_tab_id: payer || null, payer_label: payerLabel || (payerTab ? guestTabLabel(payerTab) : ""), recipient_id: recipient || null };
      if (mode === "tip_only") { if (!payer || !newTip) return { input: null, problem: "Gast und positives zusätzliches Trinkgeld auswählen." }; input.mode = "tip_only"; }
      else if (mode === "equal" && plan) { if (plan.status !== "open") return { input: null, problem: "Diese Aufteilung ist nicht offen. Bitte den Verlauf oder eine neue Restaufteilung verwenden." }; if (!parts.length) return { input: null, problem: "Einen offenen Zahleranteil auswählen." }; input.mode = "parts"; input.part_ids = parts; }
      else {
        if (!visitId && !planBase) return { input: null, problem: "Zuerst einen Besuch auswählen." };
        input.scope = mode === "guests" ? { guest_tab_ids: guests } : { visit_id: visitId };
        if (mode === "guests" && !guests.length) return { input: null, problem: "Mindestens einen Gast auswählen." };
        if (mode === "units" || (mode === "equal" && planBase)) { input.mode = "units"; input.units = mode === "equal" ? planBase! : selectedUnitAmounts(balance?.units ?? [], chosen); if (!input.units.length) return { input: null, problem: "Mindestens eine offene Position auswählen." }; input.scope = { order_ids: [...new Set(input.units.map(unit => unit.order_id))] }; }
        if (mode === "amount") { input.mode = "amount"; input.amount_cents = euroCents(amount); if (!input.amount_cents) return { input: null, problem: "Bitte einen positiven Teilbetrag eingeben." }; }
      }
      return { input, problem: "" };
    } catch (cause) { return { input: null, problem: message(cause) }; }
  }, [mode, plan, parts, tip, payer, payerLabel, recipient, visit, visitId, guests, planBase, balance, chosen, amount, otherVisits]);
  const selectionKey = selection.input ? JSON.stringify(selection.input) : "";
  useEffect(() => {
    let active = true;
    setQuote(null); setQuoteError("");
    if (!selectionKey || locked) { setQuoting(false); return; }
    const scope = principal(), input = JSON.parse(selectionKey) as PaymentSelection;
    setQuoting(true);
    const timer = setTimeout(() => {
      void venueApi<PaymentQuote>(venue.id, "/payment-groups/preview", "POST", input).then(value => { if (active && scope === principal()) setQuote({ key: selectionKey, input, value }); }).catch(cause => { if (active && scope === principal()) setQuoteError(message(cause)); }).finally(() => { if (active && scope === principal()) setQuoting(false); });
    }, 180);
    return () => { active = false; clearTimeout(timer); };
  }, [venue.id, selectionKey, locked, refresh]);
  const currentQuote = quote?.key === selectionKey ? quote : null;
  const quoted = currentQuote?.value;
  const payable = !!quoted && quoted.amount_cents > 0 && !quoted.blockers.length;
  const cashGiven = received === "" ? quoted?.amount_cents ?? null : euroCents(received);
  async function switchVisit(id: string) {
    if (locked) return;
    visitRef.current = id; setVisitId(id); rememberNavigation(id); choosePlan(null, false); setParts([]); setChosen({}); setGuests([]); setPayer(""); setPayerLabel(""); setMode("all"); setTip("0"); setReceived(""); setQuote(null); setLast(null); setPlanBase(null); setReplacement(null); setPlanContext(""); othersRef.current = []; setOtherVisits([]); setOtherBalances({});
    try { await load(); } catch (cause) { setError(message(cause)); }
  }
  function switchMode(next: Mode) { setMode(next); setQuote(null); setQuoteError(""); setLast(null); if (next !== "equal") setPlanBase(null); }
  async function selectSavedPlan(id: string) {
    if (locked) return;
    const scope = principal(); setLoading(true);
    try {
      const value = await venueApi<EqualPlan>(venue.id, `/equal-split-plans/${id}`);
      const source = await readPlanSource(venue.id, value);
      if (scope === principal() && live.current) {
        showPlanSource(value, source); setPlanBase(null); setReplacement(null); setTip("0"); setQuote(null);
      }
    }
    catch (cause) { if (scope === principal()) setError(message(cause)); }
    finally { if (scope === principal()) setLoading(false); }
  }
  async function more(kind: "visits" | "balance" | "groups" | "plans" | "tips") {
    if (locked) return; const scope = principal(); setLoading(true);
    try {
      if (kind === "visits" && visits.next_before) { const next = await venueApi<ServicePage<ServiceVisit>>(venue.id, `/service-visits?active=false&limit=50&before=${visits.next_before}`); if (scope === principal() && live.current) setVisits(current => ({ ...next, items: [...current.items, ...next.items] })); }
      if (kind === "balance" && balance?.next_before_order_id) { const next = await venueApi<PaymentBalance>(venue.id, "/payment-groups/balance", "POST", { scope: { visit_id: visitId }, before_order_id: balance.next_before_order_id, limit: 50 }); if (scope === principal() && live.current) setBalance(current => current ? { ...next, orders: [...current.orders, ...next.orders], units: [...current.units, ...next.units], remaining_cents: current.remaining_cents + next.remaining_cents, refund_due_cents: current.refund_due_cents + next.refund_due_cents, blockers: [...current.blockers, ...next.blockers] } : next); }
      if (kind === "groups") { const next = await venueApi<PaymentGroup[]>(venue.id, `/payment-groups?limit=50&before_id=${groups.at(-1)?.id}`); if (scope === principal() && live.current) { setGroups(current => [...current, ...next]); setMoreGroups(next.length === 50); } }
      if (kind === "plans") { const next = await venueApi<EqualPlan[]>(venue.id, `/equal-split-plans?limit=50&before_id=${plans.at(-1)?.id}`); if (scope === principal() && live.current) { setPlans(current => [...current, ...next]); setMorePlans(next.length === 50); } }
      if (kind === "tips") { const next = await venueApi<PayerTip[]>(venue.id, `/payer-tips?limit=50&before_id=${tips.at(-1)?.id}`); if (scope === principal() && live.current) { setTips(current => [...current, ...next]); setMoreTips(next.length === 50); } }
    } catch (cause) { if (scope === principal()) setError(message(cause)); }
    finally { if (scope === principal()) setLoading(false); }
  }
  const grouped = groupPaymentUnits((balance?.units ?? []).filter(unit => unit.remaining_cents > 0 && !unit.cancelled));
  const personalTabs = [visit, ...otherVisits].flatMap(value => value?.tabs.filter(tab => tab.kind === "guest") ?? []);
  async function addOtherVisit() {
    if (locked || !otherId) return; const scope = principal(); setLoading(true);
    try { const [value, nextBalance] = await Promise.all([venueApi<ServiceVisit>(venue.id, `/service-visits/${otherId}`), venueApi<PaymentBalance>(venue.id, "/payment-groups/balance", "POST", { scope: { visit_id: otherId }, limit: 50 })]); if (scope === principal() && live.current) { othersRef.current = [...othersRef.current.filter(row => row.id !== value.id), value]; setOtherVisits(othersRef.current); setOtherBalances(current => ({ ...current, [value.id]: nextBalance })); setAddingVisit(false); } }
    catch (cause) { if (scope === principal()) setError(message(cause)); } finally { if (scope === principal()) setLoading(false); }
  }
  async function prepareReplacement() {
    if (!plan || locked) return; const scope = principal(); setLoading(true);
    try {
      const originals = new Set(plan.parts.flatMap(part => part.unit_budgets).map(paymentUnitKey));
      const current = await venueApi<PaymentBalance>(venue.id, "/payment-groups/balance", "POST", { scope: { order_ids: plan.source_order_ids }, limit: 50 });
      if (current.has_more) throw new Error("Die ursprünglichen Quellen sind noch nicht vollständig geladen.");
      const units = current.units.filter(unit => originals.has(paymentUnitKey(unit)) && !unit.cancelled && unit.remaining_cents > 0).map(({ order_id, line_id, unit }) => ({ order_id, line_id, unit }));
      if (!units.length) throw new Error("In den ursprünglichen Positionen ist kein neu aufzuteilender Rest mehr offen.");
      if (live.current && scope === principal()) { setReplacement(plan); setParticipants(plan.parts.filter(part => part.remaining_cents > 0).map(part => ({ payer_tab_id: part.payer_tab_id, label: part.label }))); setPlanBase(units); choosePlan(null, false); setReplaceReason(""); setTip("0"); setQuote(null); }
    } catch (cause) { if (scope === principal()) setError(message(cause)); } finally { if (scope === principal()) setLoading(false); }
  }
  function nextPayer() {
    setLast(null); setTip("0"); setReceived(""); setPayerLabel(""); setQuote(null);
    if (plan?.status === "open") { const next = plan.parts.find(part => part.remaining_cents > 0); setParts(next ? [next.id] : []); setPayer(next?.payer_tab_id ?? ""); setPayerLabel(next?.label ?? ""); setMode("equal"); }
    else { const next = personalTabs.find(tab => balance?.units.some(unit => unit.guest_tab_id === tab.id && unit.remaining_cents > 0)); setGuests(next ? [next.id] : []); setPayer(next?.id ?? ""); setMode("guests"); }
  }
  function createPlan() {
    if (!currentQuote || !payable || locked) return;
    if (replacement && replaceReason.trim().length < 3) return;
    void mutation.send("/equal-split-plans", { selection: currentQuote.input, quote_hash: currentQuote.value.quote_hash, participants, ...(replacement ? { supersedes_id: replacement.id, reason: replaceReason } : {}) }, "Gleichaufteilung gespeichert.");
  }
  return <div className="fp-visit-payments">
    <section className="fp-panel">
      <div className="fp-section-head"><div><h2>Gemeinsam oder einzeln kassieren</h2><p>Gäste und Geldanteile auswählen. Originalbons bleiben erhalten.</p></div><button className="fp-button" onClick={onManage} disabled={mutation.busy || !!mutation.pending || mutation.blocked}>Schichtkasse verwalten</button></div>
      {(error || mutation.error) && <p role="alert" className="fp-notice error">{error || mutation.error}</p>}
      {mutation.pending && <div className="fp-notice" role="status"><strong>Bestätigung ausstehend</strong><p>{mutation.pending.label} Auswahl, Betrag und Vorgangs-ID bleiben für die Klärung unverändert.</p><button className="fp-button" disabled={mutation.busy || mutation.blocked} onClick={() => void mutation.retry()}><RefreshCw size={17} /> Zahlungsvorgang erneut prüfen</button></div>}
      <div className="fp-two"><Field label="Besuch kassieren"><select value={visitId} disabled={locked} onChange={event => void switchVisit(event.target.value)}><option value="">Besuch wählen</option>{[...(visit && !visits.items.some(value => value.id === visit.id) ? [visit] : []), ...visits.items].map(value => <option key={value.id} value={value.id}>{visitLabel(value)}{value.ended_at ? " · beendet" : ""}</option>)}</select></Field><Field label="Eigene offene Schichtkasse"><select disabled={locked} value={sessionId} onChange={event => setSessionId(event.target.value)}><option value="">Schichtkasse wählen</option>{sessions.filter(session => session.status === "open" && session.operator_id === userId).map(session => <option key={session.id} value={session.id}>{registers.find(register => register.id === session.register_id)?.name ?? "Kasse"}</option>)}</select></Field></div>
      {visits.has_more && <button className="fp-text-button" disabled={locked} onClick={() => void more("visits")}>Ältere Besuche laden</button>}
      {legacyRecovery.legacy&&<p className="fp-notice" role="status">Zuerst den ausstehenden Einzelbonvorgang unter „Einzelbon & Schichtkasse“ prüfen.</p>}
      {!sessionId && !loading && <p className="fp-notice">Zum Bestätigen zuerst eine eigene Schichtkasse öffnen. Auswahl und Vorschau sind bereits möglich.</p>}
      {loading && !balance && <Loading />}
      {balance && <><div className="fp-payment-totals"><div><small>{balance.has_more ? "Geladene Bons: noch offen" : plan || replacement ? "Geprüfte Originalbons: noch offen" : "Im Besuch noch offen"}</small><strong>{money(balance.remaining_cents)}</strong></div><div><small>Genehmigt, noch zurückzuzahlen</small><strong>{money(balance.refund_due_cents)}</strong></div></div>{balance.has_more && <p className="fp-notice">Die Summen gelten für die bisher geladenen Bons. Weitere Originalbons gehören zu diesem Besuch. Eine Zahlung prüft höchstens 50 Bons und 1000 Einheiten; bei größeren Besuchen gezielt Gäste oder Positionen wählen. <button className="fp-button" disabled={locked} onClick={() => void more("balance")}>Weitere Bons laden</button></p>}<details className="fp-run"><summary>Originalbons & offene Erstattungen ({balance.orders.length})</summary>{balance.orders.map(order => <div className="fp-list-row" key={order.order_id}><div><strong>{order.number}</strong><small>{labels[order.fulfillment_status] ?? order.fulfillment_status} · {labels[order.payment_status] ?? order.payment_status} · offen {money(order.remaining_cents)}</small>{order.refund_due_cents > 0 && <small>Noch zurückzuzahlen {money(order.refund_due_cents)}</small>}{order.checkout_blocked && <small>Ursprünglicher Kassenauftrag muss abgeglichen werden.</small>}</div><button className="fp-button" onClick={() => onOrder(order.order_id)}>Bon & Storno</button></div>)}</details></>}
    </section>
    {(visit || plan || replacement) && <div className="fp-payment-layout"><section className="fp-panel fp-payment-choice"><div className="fp-tabs" aria-label="Zahlung aufteilen">{([["all", "Alles zusammen"], ["guests", "Nach Gästen"], ["units", "Positionen auswählen"], ["equal", "Gleichmäßig teilen"]] as const).map(([id, label]) => <button key={id} disabled={locked} aria-pressed={mode === id} className={mode === id ? "active" : ""} onClick={() => switchMode(id)}>{label}</button>)}</div><div className="fp-inline wrap"><button className="fp-text-button" disabled={locked} onClick={() => switchMode("amount")}>Anderen Betrag</button><button className="fp-text-button" disabled={locked} onClick={() => switchMode("tip_only")}>Nur Trinkgeld</button><button className="fp-text-button" disabled={locked} onClick={() => { setRefresh(value => value + 1); void load().catch(cause => setError(message(cause))); }}>Beträge aktualisieren</button></div>
      {mode === "all" && <p>Alle offenen Beträge dieses Besuchs. Noch nicht servierte oder gesperrte Bons werden vor dem Kassieren ausdrücklich angezeigt.</p>}
      {mode === "guests" && <><p>Wähle die Gäste, deren offene Beträge diese Person übernimmt. Besuche werden dadurch nicht zusammengeführt.</p>{[visit,...otherVisits].filter((value):value is ServiceVisit=>!!value).map(value=><section key={value.id} className="fp-payment-visit-scope"><h3>{visitLabel(value)}{value.id!==visitId?" · zusätzlicher Besuch":""}</h3><div className="fp-pay-guests">{value.tabs.map(tab=>{const source=value.id===visitId?balance:otherBalances[value.id], remaining=source?.units.filter(unit=>unit.guest_tab_id===tab.id).reduce((sum,unit)=>sum+unit.remaining_cents,0)??0;return <button key={tab.id} className={`fp-pay-guest ${guests.includes(tab.id)?"selected":""}`} disabled={locked} aria-label={`${guestTabLabel(tab)} aus ${visitLabel(value)} auswählen`} aria-pressed={guests.includes(tab.id)} onClick={()=>{setGuests(values=>values.includes(tab.id)?values.filter(id=>id!==tab.id):[...values,tab.id]);if(!payer)setPayer(tab.id);}}><span>{guests.includes(tab.id)&&<Check size={17}/>} {guestTabLabel(tab)}</span><strong>{money(remaining)}</strong><small>{source?.has_more?"Rest in geladenen Bons":"Noch offen"}</small></button>;})}</div>{otherBalances[value.id]?.has_more&&<p>Weitere Bons dieses Besuchs sind vorhanden. Die serverseitige Vorschau prüft die vollständige Gastauswahl.</p>}</section>)}<button className="fp-button" disabled={locked} onClick={()=>setAddingVisit(true)}>Gäste aus anderem Besuch hinzufügen</button></>}
      {mode === "amount" && <><Field label="Gewünschter Teilbetrag in €"><input inputMode="decimal" value={amount} disabled={locked} onChange={event => setAmount(event.target.value)} placeholder="0,00" /></Field><p>Der Betrag wird auf die offenen Originalpositionen verteilt. Für einen Anteil an genau einer Flasche deren Position auswählen.</p></>}
      {mode === "units" && <><p>Antippen wählt ein Stück. Bei mehreren Stücken die Anzahl anpassen. „Geldanteil“ verändert nur die Zahlung.</p><div className="fp-inline wrap"><button className="fp-button" disabled={locked || !grouped.length} onClick={() => setChosen(Object.fromEntries(grouped.flat().map(unit => [paymentUnitKey(unit), ""])))}>Alle geladenen offenen Positionen</button><button className="fp-button" disabled={locked || !Object.keys(chosen).length} onClick={() => setChosen({})}>Auswahl leeren</button></div>{grouped.map(units => {
        const first = units[0], count = units.filter(unit => Object.hasOwn(chosen, paymentUnitKey(unit))).length;
        return <article className="fp-payment-line" key={`${first.order_id}:${first.line_id}:${first.guest_tab_id}`}><button className={`fp-payment-line-pick ${count ? "selected" : ""}`} disabled={locked} aria-pressed={count > 0} aria-label={`${first.name} für ${first.guest_label} auswählen`} onClick={() => setChosen(current => { const next = { ...current }; if (count) units.forEach(unit => delete next[paymentUnitKey(unit)]); else next[paymentUnitKey(first)] = ""; return next; })}><strong>{first.name}</strong><small>{first.guest_label} · {first.order_number}</small><span>{units.length} Stück · zusammen noch {money(units.reduce((sum, unit) => sum + unit.remaining_cents, 0))}</span></button><div className="fp-quantity"><button disabled={locked || !count} aria-label={`${first.name} ein Stück weniger auswählen`} onClick={() => setChosen(current => { const next = { ...current }, unit = [...units].reverse().find(value => Object.hasOwn(next, paymentUnitKey(value))); if (unit) delete next[paymentUnitKey(unit)]; return next; })}><Minus size={16} /></button><span>{count} von {units.length}</span><button disabled={locked || count === units.length} aria-label={`${first.name} ein Stück mehr auswählen`} onClick={() => setChosen(current => { const next = { ...current }, unit = units.find(value => !Object.hasOwn(next, paymentUnitKey(value))); if (unit) next[paymentUnitKey(unit)] = ""; return next; })}><Plus size={16} /></button></div>{units.filter(unit => Object.hasOwn(chosen, paymentUnitKey(unit))).map(unit => <details className="fp-payment-fraction" key={paymentUnitKey(unit)}><summary>Geldanteil · Stück {unit.unit + 1} · noch {money(unit.remaining_cents)}</summary><Field label={`Geldanteil für ${unit.name}, Stück ${unit.unit + 1}, in €`}><input disabled={locked} inputMode="decimal" value={chosen[paymentUnitKey(unit)]} placeholder={euroInput(unit.remaining_cents)} onChange={event => setChosen(current => ({ ...current, [paymentUnitKey(unit)]: event.target.value }))} /></Field><button className="fp-button" disabled={locked} onClick={() => setChosen(current => ({ ...current, [paymentUnitKey(unit)]: euroInput(Math.ceil(unit.remaining_cents / 2)) }))}>Hälfte des offenen Betrags</button><small>Die physische Bestellmenge bleibt unverändert. Die Vorschau prüft Cent- und Steueranteil.</small></details>)}</article>;
      })}{!!Object.keys(chosen).length && <button className="fp-button" disabled={locked || !!selection.problem} onClick={() => { try { setPlanBase(selectedUnitAmounts(balance?.units ?? [], chosen)); choosePlan(null); setMode("equal"); setTip("0"); } catch (cause) { setError(message(cause)); } }}>Auswahl gleichmäßig teilen</button>}</>}
      {mode === "equal" && <>{planContext&&<p className="fp-notice" role="status">{planContext}</p>}{plan ? <><div className="fp-section-head"><h3>Gespeicherte Aufteilung · Stand {plan.revision}</h3><Tag tone={plan.status === "open" ? "green" : "amber"}>{planStatus[plan.status]}</Tag></div><p>Plan {money(plan.total_cents)} · bezahlt {money(plan.paid_cents)} · offen {money(plan.remaining_cents)}. Zusätzliche Runden und Trinkgeld ändern diesen Plan nicht.</p>{plan.blockers.map((blocker, index) => <p key={index} role="status" className="fp-notice error">{blocker.message}</p>)}<label className="fp-check"><input type="checkbox" checked={combineParts} disabled={locked} onChange={event=>{setCombineParts(event.target.checked);if(!event.target.checked)setParts(current=>current.slice(0,1));}}/> Mehrere Zahleranteile zusammen bezahlen</label><div className="fp-pay-guests" aria-label="Gespeicherte Zahleranteile">{plan.parts.map(part => <button key={part.id} className={`fp-pay-guest ${parts.includes(part.id) ? "selected" : ""}`} aria-pressed={parts.includes(part.id)} disabled={locked || plan.status !== "open" || !part.remaining_cents} onClick={() => { setParts(current => combineParts ? current.includes(part.id) ? current.filter(id => id !== part.id) : [...current, part.id] : [part.id]); setPayer(part.payer_tab_id ?? ""); setPayerLabel(part.label); }}><span>{part.label || `Zahler ${part.ordinal}`}</span><strong>{money(part.remaining_cents)} offen</strong><small>Ziel {money(part.target_cents)} · bezahlt {money(part.paid_cents)}</small></button>)}</div><div className="fp-inline wrap"><button className="fp-button" disabled={locked} onClick={nextPayer}>Nächster Zahler</button>{plan.next_plan_id && <button className="fp-button" disabled={locked} onClick={() => void selectSavedPlan(plan.next_plan_id!)}>Nachfolgende Aufteilung öffnen</button>}{["open", "stale"].includes(plan.status)&&<button className="fp-button" disabled={locked} onClick={()=>void prepareReplacement()}>Rest neu aufteilen</button>}{["open", "stale"].includes(plan.status) && <button className="fp-button" disabled={locked} onClick={() => setAbandon(true)}>Restaufteilung beenden</button>}<button className="fp-button" disabled={locked} onClick={() => { choosePlan(null); setPlanBase(null); setReplacement(null); setReplaceReason(""); }}>Neue Aufteilung vorbereiten</button></div></> : <><h3>{replacement?"Restaufteilung neu prüfen":planBase ? "Ausgewählte Positionen gleichmäßig teilen" : "Offenen Besuch gleichmäßig teilen"}</h3>{replacement&&<><p>Neue Revision zu Aufteilung {replacement.id.slice(0,8)}. Bereits bezahlte Anteile bleiben im alten Verlauf.</p><Field label="Grund der neuen Restaufteilung"><input value={replaceReason} disabled={locked} minLength={3} maxLength={300} onChange={event=>setReplaceReason(event.target.value)} required/></Field></>}<div className="fp-inline"><button className="fp-button" aria-label="Ein Zahler weniger" disabled={locked || participants.length <= 2} onClick={() => setParticipants(current => current.slice(0, -1))}><Minus size={17} /></button><strong>{participants.length} Zahler</strong><button className="fp-button" aria-label="Ein Zahler mehr" disabled={locked || participants.length >= 100} onClick={() => setParticipants(current => [...current, { payer_tab_id: null, label: `Zahler ${current.length + 1}` }])}><Plus size={17} /></button></div>{participants.map((person, index) => <div className="fp-two" key={index}><Field label={`Name für Zahler ${index + 1} (optional)`}><input value={person.label} maxLength={80} disabled={locked} onChange={event => setParticipants(current => current.map((row, position) => position === index ? { ...row, label: event.target.value } : row))} /></Field><Field label={`Gastzuordnung für Zahler ${index + 1}`}><select value={person.payer_tab_id ?? ""} disabled={locked} onChange={event => setParticipants(current => current.map((row, position) => position === index ? { ...row, payer_tab_id: event.target.value || null } : row))}><option value="">Ohne Gastzuordnung</option>{personalTabs.map(tab => <option value={tab.id} key={tab.id}>{guestTabLabel(tab)}</option>)}</select></Field></div>)}<p>Die Centziele werden dauerhaft gespeichert. Eine Aufteilung bestätigt noch keine Zahlung.</p><button className="fp-button primary wide" disabled={locked || !payable || participants.length<2 || (!!replacement&&replaceReason.trim().length<3) || !!quoted?.new_tip_cents || participants.some((person, index) => person.payer_tab_id && participants.slice(0, index).some(prior => prior.payer_tab_id === person.payer_tab_id))} onClick={createPlan}>Gleichaufteilung speichern</button></>}</>}
    </section><aside className="fp-panel fp-payment-confirm" aria-label="Zahlungsvorschau">
      <h2>{mode === "equal" && !plan ? "Aufteilung prüfen" : mode === "tip_only" ? "Zusätzliches Trinkgeld" : "Dieser Zahler"}</h2>
      {!(mode === "equal" && !plan) && <><Field label="Wer zahlt?"><select value={payer} disabled={locked} onChange={event => { setPayer(event.target.value); setPayerLabel(""); }}><option value="">Andere Person / ohne Name</option>{personalTabs.map(tab => <option key={tab.id} value={tab.id}>{guestTabLabel(tab)}</option>)}</select></Field><Field label="Belegname (optional)"><input value={payerLabel} disabled={locked} maxLength={80} onChange={event => setPayerLabel(event.target.value)} /></Field><div className="fp-tip-choice"><strong>Neues Trinkgeld dieses Zahlers</strong><div className="fp-inline wrap"><button className="fp-button" disabled={locked} onClick={() => setTip("0")}>Keins</button><button className="fp-button" disabled={locked || !quoted} onClick={() => setTip(euroInput(quoted ? (100 - quoted.receipt_amount_cents % 100) % 100 : 0))}>Auf volle Euro aufrunden</button></div><Field label="Zusätzliches Trinkgeld in €"><input inputMode="decimal" value={tip} disabled={locked} onChange={event => setTip(event.target.value)} /></Field><details><summary>Trinkgeldempfänger</summary><Field label="Teammitglied für dieses Trinkgeld"><select value={recipient} disabled={locked} onChange={event => setRecipient(event.target.value)}><option value="">Kassierende Bedienung</option>{members.filter(member => member.active).map(member => <option key={member.user_id} value={member.user_id}>{member.full_name}</option>)}</select></Field></details></div></>}
      {(selection.problem || quoteError) && <p className="fp-notice" role="status">{selection.problem || quoteError}</p>}{quoting && <p role="status">Beträge werden geprüft …</p>}
      {quoted && <><div className="fp-total"><span>Ausgewählte Bonanteile</span><strong>{money(quoted.receipt_amount_cents)}</strong></div>{quoted.allocations.some(row => row.kind === "tip") && <p>Enthält vorhandenes Bon-Trinkgeld: {money(quoted.allocations.filter(row => row.kind === "tip").reduce((sum, row) => sum + row.amount_cents, 0))}.</p>}<div className="fp-total"><span>Neues Trinkgeld</span><strong>{money(quoted.new_tip_cents)}</strong></div><div className="fp-total fp-payment-now"><span>Jetzt erhalten</span><strong>{money(quoted.amount_cents)}</strong></div><small>Quellenrest vor Zahlung {money(quoted.selected_remaining_cents)} · danach {money(Math.max(0,quoted.selected_remaining_cents-quoted.receipt_amount_cents))}. Neues Trinkgeld verändert die alte Forderung nicht.</small>{quoted.blockers.map((blocker, index) => <p key={index} className="fp-notice error" role="status">{blocker.message}</p>)}<details className="fp-run"><summary>Positionen und Steueranteile prüfen</summary>{quoted.allocations.map(row => <p key={`${row.order_id}:${row.line_id}:${row.unit}`}>{row.name} · Stück {row.unit + 1}: {money(row.amount_cents)} · Steueranteil {money(row.tax_cents)}</p>)}</details></>}
      {!(mode === "equal" && !plan) && <form onSubmit={event => { event.preventDefault(); if (!currentQuote || !payable || cashGiven === null || cashGiven < currentQuote.value.amount_cents || locked || !sessionId) return; void mutation.send("/payment-groups/cash", { quote: currentQuote.input, quote_hash: currentQuote.value.quote_hash, session_id: sessionId, received_cents: cashGiven, confirmed: true }, "Bargeldzahlung bestätigen."); }}><fieldset className="fp-cancellation-fieldset" disabled={locked}><Field label="Gegeben in € (optional)"><input inputMode="decimal" value={received} placeholder={quoted ? euroInput(quoted.amount_cents) : "0,00"} onChange={event => setReceived(event.target.value)} /></Field>{quoted && cashGiven !== null && cashGiven >= quoted.amount_cents && <p>Rückgeld: <strong>{money(cashGiven - quoted.amount_cents)}</strong></p>}<button className="fp-button primary wide" disabled={!payable || !sessionId || cashGiven === null || cashGiven < (quoted?.amount_cents ?? 0)}><Banknote size={18} />{quoted ? `${money(quoted.amount_cents)} Bargeld erhalten` : "Bargeld erhalten"}</button><small>Bestätigt die tatsächliche Bargeldübergabe. Hier wird keine Kartenzahlung ausgelöst.</small></fieldset></form>}
      {last && <div className="fp-payment-receipt" role="status"><strong>Bargeld bestätigt · {money(last.amount_cents)}</strong><p>{last.payer_label || "Zahler ohne Name"} · gegeben {money(last.received_cents)} · Rückgeld {money(last.change_cents)}</p><small>Bonanteile {money(last.receipt_amount_cents)} · neues Trinkgeld {money(last.new_tip_cents)} · Beleg {last.id.slice(0, 8)}</small><button className="fp-button" disabled={locked} onClick={nextPayer}>Nächster Zahler</button></div>}
    </aside></div>}
    <section className="fp-panel"><h2>Aufteilungen und Zahlungsverlauf im Betrieb</h2><details className="fp-run"><summary>Gespeicherte Aufteilungen</summary>{plans.map(value => <div className="fp-list-row" key={value.id}><div><strong>{date(value.created_at, venue.timezone)} · {value.parts.map(part => part.label).join(", ")}</strong><small>{planStatus[value.status]} · {money(value.remaining_cents)} offen · {value.id.slice(0, 8)}</small></div><button className="fp-button" disabled={locked} onClick={() => void selectSavedPlan(value.id)}>Aufteilung öffnen</button></div>)}{morePlans && <button className="fp-button" disabled={locked} onClick={() => void more("plans")}>Ältere Aufteilungen laden</button>}</details><details className="fp-run"><summary>Bestätigte gemeinsame Zahlungen</summary>{groups.map(group => <details className="fp-run" key={group.id}><summary>{group.payer_label || "Zahler ohne Name"} · {money(group.amount_cents)} · {date(group.created_at, venue.timezone)} {time(group.created_at, venue.timezone)}</summary><p>Gegeben {money(group.received_cents)} · Rückgeld {money(group.change_cents)} · neues Trinkgeld {money(group.new_tip_cents)}</p><small>Gemeinsamer Beleg {group.id}</small>{group.allocations.map(row => <p key={`${row.order_id}:${row.line_id}:${row.unit}`}>{row.name} · Stück {row.unit + 1} · {money(row.amount_cents)}</p>)}{group.entries.map(entry => entry.order_id && <button key={entry.id} className="fp-button" disabled={locked} onClick={() => onOrder(entry.order_id!)}>Originalbon & Storno · {entry.id.slice(0, 8)}</button>)}</details>)}{!groups.length && !loading && <Empty title="Noch keine gemeinsamen Zahlungen">Bestätigte Vorgänge erscheinen hier mit ihren Originalquellen.</Empty>}{moreGroups && <button className="fp-button" disabled={locked} onClick={() => void more("groups")}>Ältere Zahlungen laden</button>}</details><details className="fp-run"><summary>Zusätzliches Zahler-Trinkgeld</summary>{tips.map(value => <div className="fp-list-row" key={value.id}><div><strong>{value.payer_label || "Zahler ohne Name"} · {money(value.amount_cents)}</strong><small>{date(value.created_at, venue.timezone)} · zurückgegeben {money(value.refunded_cents)}{value.tip_run_id ? " · bereits verteilt" : ""}</small>{value.reason && <small>{value.reason}</small>}</div>{venue.role === "manager" && value.refundable_cents > 0 && !value.tip_run_id && <button className="fp-button" disabled={locked} onClick={() => setReturnTip(value)}>Trinkgeld zurückgeben</button>}</div>)}{moreTips && <button className="fp-button" disabled={locked} onClick={() => void more("tips")}>Ältere Trinkgeldbelege laden</button>}</details></section>
    {addingVisit&&<Modal title="Gäste aus anderem Besuch" closeDisabled={loading} onClose={()=>{if(!loading)setAddingVisit(false);}}><p>Besuch auswählen und anschließend dessen Gäste markieren. Alle Originalbons und Besuche bleiben eigenständig.</p><Field label="Zusätzlicher Besuch"><select value={otherId} disabled={locked} onChange={event=>setOtherId(event.target.value)}><option value="">Besuch wählen</option>{visits.items.filter(value=>value.id!==visitId&&!otherVisits.some(row=>row.id===value.id)).map(value=><option key={value.id} value={value.id}>{visitLabel(value)}</option>)}</select></Field>{visits.has_more&&<button className="fp-button" disabled={locked} onClick={()=>void more("visits")}>Ältere Besuche laden</button>}<button className="fp-button primary wide" disabled={locked||!otherId} onClick={()=>void addOtherVisit()}>Gäste dieses Besuchs anzeigen</button>{error&&<p role="alert">{error}</p>}</Modal>}
    {abandon && plan && <Modal title="Offene Aufteilung beenden" closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setAbandon(false); }}><p>Bereits bezahlte Anteile bleiben erhalten. Der noch offene Bonbetrag wird dadurch nicht erlassen.</p><form onSubmit={event => { event.preventDefault(); void mutation.send(`/equal-split-plans/${plan.id}/actions`, { action: "abandon", reason: str(new FormData(event.currentTarget), "reason") }, "Restaufteilung beendet."); }}><fieldset className="fp-cancellation-fieldset" disabled={locked}><Field label="Grund"><input name="reason" minLength={3} maxLength={300} required /></Field><button className="fp-button primary wide">Aufteilung beenden</button></fieldset></form>{mutation.error && <p role="alert">{mutation.error}</p>}</Modal>}
    {returnTip && <Modal title="Trinkgeld tatsächlich zurückgeben" closeDisabled={mutation.busy} onClose={() => { if (!mutation.busy) setReturnTip(null); }}><p>Originalbeleg {returnTip.id.slice(0, 8)} · noch rückgebbar {money(returnTip.refundable_cents)}. Die Rückgabe wird als eigener Bargeldbeleg erfasst.</p><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget), amount = euroCents(str(form, "amount")); if (!amount || amount > returnTip.refundable_cents) return; void mutation.send(`/payer-tips/${returnTip.id}/returns`, { session_id: sessionId, amount_cents: amount, reason: str(form, "reason"), confirmed: true }, "Tatsächliche Trinkgeldrückgabe bestätigt."); }}><fieldset className="fp-cancellation-fieldset" disabled={locked || !sessionId}><Field label="Rückgabe in €"><input name="amount" inputMode="decimal" defaultValue={euroInput(returnTip.refundable_cents)} required /></Field><Field label="Grund der Trinkgeldrückgabe"><input name="reason" minLength={3} maxLength={300} required /></Field><label className="fp-check"><input type="checkbox" required /> Ich bestätige die tatsächliche Bargeldübergabe.</label><button className="fp-button primary wide">Trinkgeldrückgabe bestätigen</button></fieldset></form>{mutation.error && <p role="alert">{mutation.error}</p>}</Modal>}
  </div>;
}
