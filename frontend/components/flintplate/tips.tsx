"use client";
import { useCallback, useEffect, useState } from "react";
import { Coins, HandCoins, Info } from "lucide-react";
import { message, money, str, time, day, venueApi, type TipDistribution, type TipRun, type Venue } from "@/lib/flintplate";
import { Empty, Field, Tag } from "./shared";

const today = (zone:string) => new Intl.DateTimeFormat("en-CA", {timeZone:zone, year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const label = (pool:string) => pool==="kitchen"?"Küche":pool==="direkt"?"Direkt":pool==="gemischt"?"Mehrere Anteile":"Service";
type TipPreview = TipDistribution & {allocated_cents:number; open_cents:number};
type TimeAttribution = {entry_id:string;shift_id:string;worker_id:string;full_name:string;starts_at:string;ends_at:string;station:string;minutes:number;attributed:boolean};

/** Tips are distributed on paid bills only, by the rule the venue configured. */
export function TipPayouts({venue}:{venue:Venue}){
 return <TipPayoutsView key={venue.id} venue={venue}/>;
}

function TipPayoutsView({venue}:{venue:Venue}){
 const [runs,setRuns]=useState<TipRun[]>([]);
 const [preview,setPreview]=useState<TipPreview|null>(null);
 const [attributions,setAttributions]=useState<TimeAttribution[]>([]);
 const [period,setPeriod]=useState({start:today(venue.timezone),end:today(venue.timezone)});
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");

 const reload=useCallback(async()=>{setRuns(await venueApi<TipRun[]>(venue.id,"/tips/runs"));},[venue.id]);
 useEffect(()=>{reload().catch(e=>setError(message(e)));},[reload]);

 async function loadPeriod(next:{start:string;end:string}){
  const [distribution,times]=await Promise.all([
   venueApi<TipPreview>(venue.id,"/tips/preview","POST",{period_start:next.start,period_end:next.end}),
   venueApi<TimeAttribution[]>(venue.id,`/tips/time-attributions?period_start=${next.start}&period_end=${next.end}`),
  ]);
  setPreview(distribution);setAttributions(times);
 }

 async function show(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  const f=new FormData(event.currentTarget);
  const next={start:str(f,"start"),end:str(f,"end")};
  setBusy(true);setError("");setNotice("");
  try{
   setPeriod(next);
   await loadPeriod(next);
  }catch(e){setError(message(e));setPreview(null);}
  finally{setBusy(false);}
 }

 async function confirm(){
  setBusy(true);setError("");
  try{
   const run=await venueApi<TipRun>(venue.id,"/tips/runs","POST",{period_start:period.start,period_end:period.end});
   await Promise.all([reload(),loadPeriod(period)]);setNotice(`${money(run.total_cents)} festgeschrieben. Offene Beträge können später im selben Zeitraum verteilt werden.`);
  }catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 async function attribute(row:TimeAttribution){
  setBusy(true);setError("");setNotice("");
  try{
   await venueApi(venue.id,`/tips/time-attributions/${row.entry_id}/${row.shift_id}`,"PUT");
   await loadPeriod(period);setNotice(`Arbeitszeit von ${row.full_name} zugeordnet. Vorschau aktualisiert.`);
  }catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 return <section className="fp-panel">
  <div className="fp-section-head">
   <div><h2>Trinkgeld verteilen</h2><p>Nur bestätigt bezahltes Trinkgeld, nach der Regel dieser Betriebsstätte.</p></div>
   <Tag tone="green">{venue.tip_mode==="direct"?"Direkt an die Bedienung":`Topf nach Stunden${venue.tip_kitchen_bps?` · Küche ${venue.tip_kitchen_bps/100} %`:""}`}</Tag>
  </div>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  {notice&&<p className="fp-notice" role="status">{notice}</p>}

  <form onSubmit={show} className="fp-period">
   <Field label="Von"><input name="start" type="date" defaultValue={period.start} required/></Field>
   <Field label="Bis"><input name="end" type="date" defaultValue={period.end} required/></Field>
   <button className="fp-button" disabled={busy}><Coins size={16}/> Vorschau</button>
  </form>

  {preview&&<div className="fp-preview">
   <div className="fp-total"><span>Trinkgeld im Zeitraum · {preview.orders} {preview.orders===1?"Bon":"Bons"} · {preview.payer_tips??0} zusätzliche Trinkgeldbelege</span><strong>{money(preview.total_cents)}</strong></div>
   <div className="fp-total"><span>Jetzt verteilbar</span><strong>{money(preview.allocated_cents)}</strong></div>
   {preview.open_cents>0&&<div className="fp-total"><span>Bleibt offen</span><strong>{money(preview.open_cents)}</strong></div>}
   {preview.notes.map(note=><p className="fp-hint" key={note}><Info size={14}/> {note}</p>)}
   {preview.shares.length>0&&<div className="fp-table-wrap"><table>
    <thead><tr><th>Person</th><th>Topf</th><th>Freigegebene Zeit</th><th>Anteil</th><th>Grund</th></tr></thead>
    <tbody>{preview.shares.map(share=><tr key={share.worker_id}>
     <td><strong>{share.full_name}</strong></td>
     <td><Tag>{label(share.pool)}</Tag></td>
     <td>{Math.floor(share.minutes/60)} h {share.minutes%60} min</td>
     <td><strong>{money(share.share_cents)}</strong></td>
     <td><small>{share.reason}</small></td>
    </tr>)}</tbody>
   </table></div>}
   {!preview.shares.length&&<Empty title="Nichts zu verteilen">Für diesen Zeitraum gibt es kein bestätigtes Trinkgeld oder noch keine freigegebenen, zugeordneten Arbeitszeiten.</Empty>}
   {preview.shares.some(share=>share.share_cents>0)&&<button className="fp-button primary wide" disabled={busy} onClick={()=>void confirm()}><HandCoins size={17}/> Verteilung festschreiben</button>}
   <h3 className="fp-subhead">Arbeitszeiten den Diensten zuordnen</h3>
   <p>Nur durch die Personalverwaltung freigegebene Zeiten zählen. Ordne sie dem tatsächlich geleisteten Dienst zu. Änderungen an Zeit oder Dienst erfordern eine neue Zuordnung.</p>
   {attributions.map(row=><div className="fp-list-row" key={`${row.entry_id}-${row.shift_id}`}>
    <div><strong>{row.full_name} · {row.station}</strong><small>{day(row.starts_at,venue.timezone)} · {time(row.starts_at,venue.timezone)}–{time(row.ends_at,venue.timezone)} · {row.minutes} Min. im Zeitraum</small></div>
    {row.attributed?<Tag tone="green">Zugeordnet</Tag>:<button className="fp-button" disabled={busy} onClick={()=>void attribute(row)}>Diesem Dienst zuordnen</button>}
   </div>)}
   {!attributions.length&&<p className="fp-hint">Keine freigegebenen Zeiten mit passendem veröffentlichtem Dienst vorhanden.</p>}
  </div>}

  <h3 className="fp-subhead">Bisherige Verteilungen</h3>
  {runs.map(run=><details className="fp-run" key={run.id}>
   <summary><strong>{run.period_start === run.period_end ? run.period_start : `${run.period_start} bis ${run.period_end}`}</strong><span>{money(run.total_cents)} · {run.orders} Bons · {run.payer_tips??0} zusätzliche Trinkgeldbelege · {run.mode==="direct"?"direkt":"nach Stunden"}</span></summary>
   <ul>{run.shares.map(share=><li key={share.worker_id}><span>{share.full_name} · {label(share.pool)}</span><strong>{money(share.share_cents)}</strong></li>)}</ul>
  </details>)}
  {!runs.length&&<Empty title="Noch nichts verteilt">Wähle einen Zeitraum und sieh dir die Vorschau an.</Empty>}
 </section>;
}
