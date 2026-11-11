"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useCallback, useEffect, useRef, useState } from "react";
import { Banknote, RefreshCw, ShieldCheck } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { loadOrderFeed } from "@/lib/flintplate-order-feed";
import { day, message, money, num, str, venueApi, type Member, type Order, type Venue } from "@/lib/flintplate";
import { Empty, Field, Tag } from "./shared";
import { cashRecovery, cashViewForRecovery, useCashRecovery, CASH_RECOVERY_CHANGED, type CashPanelView, type CashRecovery } from "@/lib/flintplate-cash-recovery";
import { VisitPayments } from "./visit-payments";
import { OrderProvenanceButton } from "./order-provenance";
import { OrderCancellationButton } from "./order-cancellations";

type Register = { id:string; name:string };
type Session = { id:string; register_id:string; operator_id:string; status:string; version:number; created_at:string; counted_cents:number|null; expected_cents:number|null; difference_cents:number|null; count_reason:string };
type Entry = { created_at:string; id:string; kind:string; method:string; amount_cents:number; received_cents:number|null; change_cents:number|null; original_id:string|null; payer:string; reason:string; external_reference:string|null };
type Line = { cancelled_quantity:number; cancelled_cents:number; line_id:string; name:string; kind:string; remaining_quantity:number; remaining_cents:number };
type RefundClaim = { cancellation_id:string; original_id:string; method:string; amount_cents:number; tax_cents:number; refunded_cents:number; remaining_cents:number };
type Balance = { historical_cancelled:boolean; corrected_total_cents:number; cancelled_cents:number; unpaid_credit_cents:number; refund_due_cents:number; refund_claims:RefundClaim[]; checkout_blocked:boolean; cancellation_version:number|null; order_id:string; version:number; total_cents:number; voucher_cents:number; tip_cents:number; paid_cents:number; remaining_cents:number; remaining_tip_cents:number; refunded_cents:number; lines:Line[]; entries:Entry[] };
type Reconciliation = { receipts:Record<string,number>; refunds:Record<string,number>; tip_cents:number; tax_cents:number; open_sessions:number; differences_cents:number };
type Pending = { path:string; body:Record<string,unknown>; label:string };
const tender = (method:string) => ({cash:"Bargeld",external:"Extern bestätigt",voucher:"Gutschein"}[method] ?? method);
const cents = (form:FormData, name:string) => Math.round(num(form,name)*100);

function principal():string { const user=auth.getUser(); return JSON.stringify([user?.tenant_id,user?.sub]); }
function storageKey(venueId:string):string { return `flintplate:cash-pending:v1:${encodeURIComponent(principal())}:${venueId}`; }
function localDay(venue:Venue):string { return new Intl.DateTimeFormat("en-CA",{timeZone:venue.timezone,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date()); }

export function CashPanel({venue,initialOrderId="",initialVisitId="",initialGuestTabId=""}:{venue:Venue;initialOrderId?:string;initialVisitId?:string;initialGuestTabId?:string}) {
  const [view,setView]=useState<CashPanelView>(initialOrderId?"single":"guests"), [selectedOrder,setSelectedOrder]=useState(initialOrderId);
  const retainRecoveryView=useCallback((next:CashRecovery)=>setView(current=>cashViewForRecovery(current,next)),[]);
  const recovery=useCashRecovery(venue.id,retainRecoveryView);
  const activeView=cashViewForRecovery(view,recovery);
  return <>{(recovery.group||recovery.legacy)&&<div className="fp-notice" role="status"><strong>Kassenvorgang mit ausstehender Bestätigung</strong><p>Der ursprüngliche Auftrag bleibt erhalten. Vor einer weiteren Buchung zuerst abgleichen.</p>{recovery.group&&<button className="fp-button" onClick={()=>setView("guests")}>Ausstehenden gemeinsamen Kassenvorgang öffnen</button>}{recovery.legacy&&<button className="fp-button" onClick={()=>setView("single")}>Ausstehenden Einzelbonvorgang öffnen</button>}</div>}<div className="fp-tabs" aria-label="Kassenansichten"><button disabled={recovery.legacy&&!recovery.group} className={activeView==="guests"?"active":""} onClick={()=>setView("guests")}>Gäste & aufteilen</button><button disabled={recovery.group} className={activeView==="single"?"active":""} onClick={()=>setView("single")}>Einzelbon & Schichtkasse</button></div>{activeView==="guests"?<VisitPayments venue={venue} initialVisitId={initialVisitId} initialGuestTabId={initialGuestTabId} onManage={()=>setView("single")} onOrder={id=>{setSelectedOrder(id);setView("single");}}/>:<CashView key={`${venue.id}:${selectedOrder}`} venue={venue} initialOrderId={selectedOrder}/>}</>;
}

function CashView({venue,initialOrderId}:{venue:Venue;initialOrderId:string}) {
  const [registers,setRegisters]=useState<Register[]>([]);
  const [sessions,setSessions]=useState<Session[]>([]);
  const [members,setMembers]=useState<Member[]>([]);
  const [orders,setOrders]=useState<Order[]>([]);
  const [orderId,setOrderId]=useState(initialOrderId);
  const orderRef=useRef(initialOrderId);
  const [sessionId,setSessionId]=useState("");
  const [balance,setBalance]=useState<Balance|null>(null);
  const [mode,setMode]=useState("amount");
  const [report,setReport]=useState<Reconciliation|null>(null);
  const [reportDay,setReportDay]=useState(()=>localDay(venue));
  const [pending,setPending]=useState<Pending|null>(null);
  const pendingRef=useRef<Pending|null>(null);
  const scopeRef=useRef("");
  const busyRef=useRef(false);
  const [ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const manager=venue.role==="manager";
  const sharedRecovery=useCashRecovery(venue.id);

  const load=useCallback(async()=>{
    const scope=principal();
    const [nextRegisters,nextSessions,nextMembers,nextOrders]=await Promise.all([
      venueApi<Register[]>(venue.id,"/cash/registers"),
      venueApi<Session[]>(venue.id,"/cash/sessions"),
      venueApi<Member[]>(venue.id,"/members"),
      loadOrderFeed(venue.id),
    ]);
    if(orderRef.current&&!nextOrders.some(order=>order.id===orderRef.current))nextOrders.push(await venueApi<Order>(venue.id,`/orders/${orderRef.current}`));
    if(scope!==principal()) return;
    setRegisters(nextRegisters);setSessions(nextSessions);setMembers(nextMembers);setOrders(nextOrders);
    setSessionId(current=>nextSessions.some(s=>s.id===current&&s.status==="open")?current:nextSessions.find(s=>s.status==="open")?.id??"");
  },[venue.id]);

  useEffect(()=>{
    let active=true;
    async function initialize(){
      scopeRef.current=principal();
      const raw=localStorage.getItem(storageKey(venue.id));
      let restored:Pending|null=null;
      try {
        const parsed:unknown=raw?JSON.parse(raw):null;
        if(parsed&&typeof parsed==="object"&&"path" in parsed&&typeof parsed.path==="string"&&parsed.path.startsWith("/")&&"body" in parsed&&parsed.body&&typeof parsed.body==="object"&&"label" in parsed&&typeof parsed.label==="string") restored=parsed as Pending;
      } catch { localStorage.removeItem(storageKey(venue.id)); }
      await load();
      if(active&&scopeRef.current===principal()){pendingRef.current=restored;setPending(restored);setReady(true);}
    }
    void initialize().catch(e=>{if(active)setError(message(e));});
    const changed=()=>{if(scopeRef.current===principal())return;pendingRef.current=null;setPending(null);setBalance(null);setReady(false);};
    window.addEventListener("palmscout-auth-changed",changed);
    window.addEventListener("storage",changed);
    return()=>{active=false;window.removeEventListener("palmscout-auth-changed",changed);window.removeEventListener("storage",changed);};
  },[load,venue.id]);

  const refreshBalance=useCallback(async()=>{
    if(!orderId){setBalance(null);return;}
    const scope=principal();
    const next=await venueApi<Balance>(venue.id,`/orders/${orderId}/balance`);
    if(scope===principal()&&orderRef.current===orderId)setBalance(next);
  },[orderId,venue.id]);
  useEffect(()=>{let active=true;void refreshBalance().catch(e=>{if(active)setError(message(e));});return()=>{active=false;};},[refreshBalance]);

  async function execute(request:Pending,retry=false){
    if(busyRef.current||scopeRef.current!==principal())return;
    busyRef.current=true;setBusy(true);setError("");setNotice("");
    const key=storageKey(venue.id), scope=principal();let committed=false;
    pendingRef.current=request;setPending(request);
    try {
      localStorage.setItem(key,JSON.stringify(request));
      window.dispatchEvent(new Event(CASH_RECOVERY_CHANGED));
      await venueApi(venue.id,request.path,"POST",request.body);committed=true;
      if(scope!==principal())return;
      await load();await refreshBalance();
      if(scope!==principal())return;
      localStorage.removeItem(key);pendingRef.current=null;setPending(null);
      setNotice(request.label);setReport(null);
    } catch(e) {
      if(scope!==principal())return;
      if(!committed&&!retry&&e instanceof ApiError&&e.status>=400&&e.status<500&&e.status!==408){localStorage.removeItem(key);pendingRef.current=null;setPending(null);}
      setError(message(e));
    } finally {busyRef.current=false;window.dispatchEvent(new Event(CASH_RECOVERY_CHANGED));if(scope===principal())setBusy(false);}
  }

  function post(path:string,body:Record<string,unknown>,label:string,withKey=true){
    if(cashRecovery(venue.id).group){setError("Zuerst den ausstehenden gemeinsamen Kassenvorgang prüfen.");return;}
    if(pendingRef.current){setError("Zuerst den ausstehenden Vorgang prüfen. Seine Vorgangs-ID bleibt erhalten.");return;}
    void execute({path,body:withKey?{...body,request_key:newRequestId()}:body,label});
  }
  const locked=busy||!ready||!!pending||sharedRecovery.group||sharedRecovery.unavailable;

  return <div>
    <section className="fp-panel">
      <div className="fp-section-head"><div><h2>Kasse</h2><p>Bargeld erfassen, Bons aufteilen und die Schicht abschließen.</p></div><Banknote size={26}/></div>
      {error&&<p className="fp-notice error" role="alert">{error}</p>}
      {notice&&<p className="fp-notice" role="status">{notice}</p>}
      {pending&&<div className="fp-notice"><p>Die Rückmeldung für einen Kassenvorgang steht aus. Bis zur Klärung bleibt seine Vorgangs-ID erhalten.</p><button className="fp-button" disabled={busy} onClick={()=>void execute(pending,true)}><RefreshCw size={16}/> Vorgang erneut prüfen</button></div>}
      {!ready&&!error&&<p>Kassen werden geladen …</p>}
      <div className="fp-two">
        <Field label="Offene Schichtkasse"><select value={sessionId} onChange={e=>setSessionId(e.target.value)} disabled={locked}><option value="">Schichtkasse wählen</option>{sessions.filter(s=>s.status==="open").map(s=><option key={s.id} value={s.id}>{registers.find(r=>r.id===s.register_id)?.name} · {members.find(m=>m.user_id===s.operator_id)?.full_name??"Bedienung"}</option>)}</select></Field>
        <Field label="Bon kassieren oder Zahlung ansehen"><select value={orderId} disabled={locked} onChange={e=>{orderRef.current=e.target.value;setBalance(null);setOrderId(e.target.value);}}><option value="">Bon wählen</option>{orders.filter(order=>["served","settled","cancelled"].includes(order.status)||order.id===orderId).map(order=><option key={order.id} value={order.id}>{order.number} · Original {money(order.total_cents)} · {order.payment_status==="refunded"?"erstattet":order.payment_status==="partially_refunded"?"teilweise erstattet":order.payment_status==="refund_pending"?"Erstattung offen":order.payment_status==="adjusted"?"Forderung korrigiert":order.payment_status==="cancelled"?"storniert":order.payment_status==="paid"?"bezahlt":order.payment_status==="partial"?"teilbezahlt":order.status==="settled"?"abgeschlossen":"offen"}</option>)}</select></Field>
      </div>
      {balance&&<>
        {orders.find(order=>order.id===balance.order_id)&&<OrderCancellationButton venue={venue} order={orders.find(order=>order.id===balance.order_id)!} members={members} onChanged={async()=>{await load();await refreshBalance();}}/>}
        <OrderProvenanceButton key={balance.order_id} venueId={venue.id} orderId={balance.order_id} number={orders.find(order=>order.id===balance.order_id)?.number??"Bon"} />
        {balance.historical_cancelled&&<p className="fp-notice" role="status">Historischer Stornodatensatz; kein positionsweiser Stornobeleg vorhanden. Es besteht keine offene Forderung. Daraus wird kein Rückzahlungsanspruch abgeleitet.</p>}
        <div className="fp-total"><span>Ursprünglicher Bon inklusive Trinkgeld</span><strong>{money(balance.total_cents+balance.tip_cents)}</strong></div>
        {balance.cancelled_cents>0&&<><div className="fp-total"><span>Genehmigte Stornos</span><strong>{money(balance.cancelled_cents)}</strong></div><div className="fp-total"><span>Bon nach Stornos inkl. verbleibendem Trinkgeld</span><strong>{money(balance.corrected_total_cents)}</strong></div><p>Verringerung der offenen Forderung: {money(balance.unpaid_credit_cents)}</p></>}
        {balance.voucher_cents>0&&<p>Gutschein: {money(balance.voucher_cents)}</p>}
        <div className="fp-total"><span>Bestätigte Zahlung ohne Gutschein</span><strong>{money(balance.paid_cents)}</strong></div>
        <div className="fp-total"><span>Noch offen</span><strong>{money(balance.remaining_cents)}</strong></div>
        {balance.refunded_cents>0&&<p>Zurückerstattet: {money(balance.refunded_cents)}</p>}
        {balance.checkout_blocked&&<p className="fp-notice" role="status">Der ursprüngliche Kassenauftrag ist noch nicht abgeglichen. Der Kassenadapter muss die Bonkorrektur und ausstehende Zahlungsbestätigungen klären, bevor weiter kassiert wird.</p>}
        {balance.remaining_cents>0&&!balance.checkout_blocked&&["served","settled"].includes(orders.find(o=>o.id===orderId)?.status??"")&&<>
          <div className="fp-tabs small" aria-label="Bon aufteilen">{[["amount","Betrag"],["equal","Personen"],["items","Positionen"]].map(([value,label])=><button key={value} disabled={locked} className={mode===value?"active":""} onClick={()=>setMode(value)}>{label}</button>)}</div>
          <form key={`${balance.order_id}:${balance.version}:${mode}`} onSubmit={e=>{
            e.preventDefault();const f=new FormData(e.currentTarget);
            const items=balance.lines.map(line=>({line_id:line.line_id,quantity:num(f,`qty:${line.line_id}`)})).filter(line=>line.quantity>0);
            const rawReceived=str(f,"received");
            post(`/orders/${orderId}/cash-payments`,{version:balance.version,session_id:sessionId,mode,
              ...(mode==="amount"?{amount_cents:cents(f,"amount")}:mode==="equal"?{people:num(f,"people")}:{items,tip_cents:cents(f,"tip")}),
              payer:str(f,"payer"),...(rawReceived?{received_cents:cents(f,"received")}:{}),
            },"Bargeld bestätigt. Restbetrag und Zahlungsliste sind aktualisiert.");
          }}>
            <fieldset disabled={locked||!sessionId} style={{border:0,padding:0,margin:0}}>
              {mode==="amount"&&<Field label="Teilbetrag in €"><input name="amount" type="number" min={balance.remaining_cents?0.01:0} max={balance.remaining_cents/100} step="0.01" defaultValue={balance.remaining_cents/100} required/></Field>}
              {mode==="equal"&&<><Field label="Verbleibende Personen"><input name="people" type="number" min={1} max={100} defaultValue={2} required/></Field><p>Der offene Betrag wird auf diese Personen geteilt. Ein verbleibender Cent wird jetzt mit kassiert.</p></>}
              {mode==="items"&&<><p>Bereits geleistete Teilbeträge sind berücksichtigt. Offene Stücke können anteilig bezahlt sein.</p>{balance.lines.filter(line=>line.remaining_quantity>0).map(line=><div className="fp-list-row" key={line.line_id}><div><strong>{line.name}</strong><small>{line.remaining_quantity} Stück · zusammen noch {money(line.remaining_cents)}</small></div><Field label={`Anzahl ${line.name}`}><input name={`qty:${line.line_id}`} type="number" min={0} max={line.remaining_quantity} defaultValue={0}/></Field></div>)}{balance.remaining_tip_cents>0&&<Field label={`Trinkgeldanteil in € (offen ${money(balance.remaining_tip_cents)})`}><input name="tip" type="number" min={0} max={balance.remaining_tip_cents/100} step="0.01" defaultValue={0}/></Field>}</>}
              <div className="fp-two"><Field label="Person / Gruppe (optional)"><input name="payer" maxLength={80} placeholder="z. B. Person 1"/></Field><Field label="Gegeben in € (optional, für Rückgeld)"><input name="received" type="number" min={0} step="0.01"/></Field></div>
              <button className="fp-button primary wide"><Banknote size={17}/> Erhaltenes Bargeld bestätigen</button>
            </fieldset>
          </form>
          {!sessionId&&<p className="fp-hint">Zum Kassieren zuerst eine eigene offene Schichtkasse wählen.</p>}
        </>}
        <section className="fp-refund-claims" aria-label="Genehmigte Rückzahlungsansprüche">
          <h3>Genehmigte Rückzahlungsansprüche</h3><p>Noch zurückzuzahlen: <strong>{money(balance.refund_due_cents)}</strong>. Eine Stornofreigabe bestätigt noch keine Auszahlung.</p>
          {(balance.refund_claims??[]).map(claim=><article className="fp-cancellation-history" key={`${claim.cancellation_id}:${claim.original_id}`}>
            <div className="fp-section-head"><div><strong>{tender(claim.method)} · Stornobeleg {claim.cancellation_id.slice(0,8)}</strong><small>Originalzahlung {claim.original_id.slice(0,8)}</small></div><Tag tone={claim.remaining_cents>0?"amber":"green"}>{claim.remaining_cents>0?"Auszahlung offen":"Ausgeglichen"}</Tag></div>
            <p>Anspruch {money(claim.amount_cents)} · bestätigt erstattet {money(claim.refunded_cents)} · noch offen <strong>{money(claim.remaining_cents)}</strong></p>
            {claim.method==="external"&&claim.remaining_cents>0&&<p className="fp-notice">Die Rückzahlung muss über den ursprünglichen Zahlungsadapter bestätigt werden. Hier wird keine externe Auszahlung ausgelöst.</p>}
            {manager&&claim.remaining_cents>0&&claim.method!=="external"&&<form onSubmit={event=>{event.preventDefault();const form=new FormData(event.currentTarget);post(`/cash/payments/${claim.original_id}/refunds`,{cancellation_id:claim.cancellation_id,amount_cents:cents(form,"refund"),reason:str(form,"reason"),confirmed:true,...(claim.method==="cash"?{session_id:sessionId}:{})},claim.method==="cash"?"Tatsächliche Barauszahlung als Gegenbuchung bestätigt.":"Guthaben auf den ursprünglichen Gutschein zurückgebucht.");}}>
              <fieldset disabled={locked||(claim.method==="cash"&&!sessionId)} className="fp-cancellation-fieldset"><div className="fp-two"><Field label="Rückerstattung in €"><input name="refund" type="number" min={0.01} max={claim.remaining_cents/100} defaultValue={claim.remaining_cents/100} step="0.01" required/></Field><Field label="Auszahlungsbegründung"><input name="reason" minLength={3} maxLength={300} required/></Field></div><label className="fp-check"><input type="checkbox" name="confirmed" required/>{claim.method==="cash"?"Ich bestätige die tatsächliche Übergabe dieses Bargeldbetrags.":"Diesen Betrag auf den ursprünglichen Gutschein zurückbuchen."}</label><button className="fp-button primary">{claim.method==="cash"?"Tatsächliche Barauszahlung bestätigen":"Gutschein zurückbuchen"}</button></fieldset>
            </form>}
            {!manager&&claim.remaining_cents>0&&<p>Die Betriebsleitung bestätigt die Rückzahlung.</p>}
          </article>)}
        </section>
        <h3 className="fp-subhead">Bestätigte Zahlungen und Rückerstattungen</h3>
        {balance.entries.map(entry=><div className="fp-run" key={entry.id}><div className="fp-list-row"><div><strong>{tender(entry.method)}{entry.payer?` · ${entry.payer}`:""}</strong><small>{entry.kind==="refund"?"Rückerstattung zum Original":entry.external_reference??"Im Kassenjournal erfasst"}</small>{entry.created_at&&<small>{day(entry.created_at,venue.timezone)} · {new Intl.DateTimeFormat("de-DE",{hour:"2-digit",minute:"2-digit",timeZone:venue.timezone}).format(new Date(entry.created_at))}</small>}{entry.reason&&<small>Grund: {entry.reason}</small>}{entry.original_id&&<small>Originalzahlung: {entry.original_id}</small>}{entry.change_cents!==null&&<small>Gegeben: {money(entry.received_cents??entry.amount_cents)} · Rückgeld: {money(entry.change_cents)}</small>}</div><strong>{money(entry.amount_cents)}</strong></div></div>)}
      </>}
    </section>

    {manager&&<section className="fp-panel"><h2>Kasse öffnen</h2><div className="fp-two"><form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);post("/cash/registers",{name:str(f,"name")},"Bargeldkasse angelegt.",false);}}><Field label="Neue Bargeldkasse"><input name="name" maxLength={80} required placeholder="z. B. Tresen" disabled={locked}/></Field><button className="fp-button" disabled={locked}>Kasse anlegen</button></form>
      <form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);post("/cash/sessions",{register_id:str(f,"register"),operator_id:str(f,"operator"),opening_cents:cents(f,"opening")},"Schichtkasse mit Anfangsbestand geöffnet.");}}><fieldset disabled={locked} style={{border:0,padding:0}}><Field label="Bargeldkasse"><select name="register" required><option value="">Wählen</option>{registers.map(register=><option key={register.id} value={register.id}>{register.name}</option>)}</select></Field><Field label="Verantwortliche Bedienung"><select name="operator" required><option value="">Wählen</option>{members.filter(m=>m.active&&m.role!=="kitchen").map(member=><option key={member.user_id} value={member.user_id}>{member.full_name}</option>)}</select></Field><Field label="Gezählter Anfangsbestand in €"><input name="opening" type="number" min={0} step="0.01" required defaultValue={0}/></Field><button className="fp-button primary">Schichtkasse öffnen</button></fieldset></form></div></section>}

    <section className="fp-panel"><h2>Schichtkassen zählen und abschließen</h2>
      {sessions.map(session=><details className="fp-run" key={session.id} open={session.status==="counted"}><summary><strong>{registers.find(r=>r.id===session.register_id)?.name??"Kasse"} · {members.find(m=>m.user_id===session.operator_id)?.full_name??"Bedienung"}</strong><span>{day(session.created_at,venue.timezone)} · {session.status==="open"?"offen":session.status==="counted"?"gezählt, Abschluss offen":"abgeschlossen"}</span></summary>
        {session.status==="open"&&<>
          {manager&&<form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);post(`/cash/sessions/${session.id}/movements`,{amount_cents:cents(f,"movement"),reason:str(f,"reason")},"Bargeldbewegung protokolliert.");}}><div className="fp-two"><Field label="Einlage (+) / Entnahme (−) in €"><input name="movement" type="number" step="0.01" required disabled={locked}/></Field><Field label="Grund"><input name="reason" minLength={3} maxLength={300} required disabled={locked}/></Field></div><button className="fp-button" disabled={locked}>Bewegung bestätigen</button></form>}
          <form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);post(`/cash/sessions/${session.id}/count`,{version:session.version,counted_cents:cents(f,"count")},"Zählung gespeichert. Die Kasse ist für weitere Zahlungen gesperrt.");}}><p>Zähle das vorhandene Bargeld. Der Sollbestand wird nach der Zählung angezeigt.</p><Field label="Gezähltes Bargeld in €"><input name="count" type="number" min={0} step="0.01" required disabled={locked}/></Field><button className="fp-button" disabled={locked}>Zählung festschreiben</button></form>
        </>}
        {session.status!=="open"&&<><div className="fp-list-row"><span>Soll {money(session.expected_cents??0)} · Gezählt {money(session.counted_cents??0)}</span><Tag tone={session.difference_cents?"amber":"green"}>Differenz {money(session.difference_cents??0)}</Tag></div>{session.count_reason&&<p>{session.count_reason}</p>}</>}
        {session.status==="counted"&&manager&&<form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);post(`/cash/sessions/${session.id}/close`,{version:session.version,reason:str(f,"reason")},"Schichtkasse abgeschlossen.",false);}}><Field label="Differenzbegründung / Abschlussnotiz"><input name="reason" minLength={session.difference_cents?3:0} required={!!session.difference_cents} maxLength={300} disabled={locked}/></Field><button className="fp-button primary" disabled={locked}><ShieldCheck size={16}/> Abschluss freigeben</button></form>}
      </details>)}
      {!sessions.length&&<Empty title="Noch keine Schichtkasse">Die Betriebsleitung eröffnet die Kasse mit ihrem Anfangsbestand.</Empty>}
    </section>

    {manager&&<section className="fp-panel"><h2>Tagesabgleich</h2><form className="fp-period" onSubmit={e=>{e.preventDefault();setError("");void venueApi<Reconciliation>(venue.id,`/cash/reconciliation?day=${reportDay}`).then(setReport).catch(e=>setError(message(e)));}}><Field label="Betriebstag"><input type="date" value={reportDay} onChange={e=>setReportDay(e.target.value)} required/></Field><button className="fp-button">Abgleich laden</button></form>{report&&<><div className="fp-table-wrap"><table><thead><tr><th>Zahlart</th><th>Bestätigt</th><th>Erstattet</th><th>Nettozufluss</th></tr></thead><tbody>{["cash","external","voucher"].map(method=><tr key={method}><td>{tender(method)}</td><td>{money(report.receipts[method]??0)}</td><td>{money(report.refunds[method]??0)}</td><td>{money((report.receipts[method]??0)-(report.refunds[method]??0))}</td></tr>)}</tbody></table></div><p>Enthaltenes Trinkgeld: {money(report.tip_cents)} · Steueranteil der Buchungen: {money(report.tax_cents)}</p><p>{report.open_sessions} Schichtkassen noch nicht abgeschlossen · Kassendifferenzen heute {money(report.differences_cents)}</p></>}</section>}
  </div>;
}
