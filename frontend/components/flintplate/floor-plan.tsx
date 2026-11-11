"use client";
import { newRequestId } from "@/lib/flintplate-uuid";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { Clock3, Layers, MapPin, Move, Pencil, Plus } from "lucide-react";
import { labels, money, num, str, time, venueApi, type Resource, type Venue } from "@/lib/flintplate";
import type { Action, Data } from "./operations";
import { Empty, Field, Modal, Tag, useNow, since } from "./shared";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { DEFAULT_FLOOR_SNAP, type FloorPoint } from "@/lib/flintplate-floor-geometry";
import { LAYOUT_PATHS } from "@/lib/flintplate-layout";
import { usesOriginalTable } from "@/lib/flintplate-visits";
import { useOrderServiceContexts, useServicePresence } from "./service-context";
import { FloorCanvas } from "./floor-canvas";
import { LayoutProfiles } from "./layout-profiles";
type FloorPlanProps={venue:Venue;data:Data;act:Action;compact?:boolean;onOrder:(id:string)=>void};
const categories=["table","bowling","billiard","pedal_boat","activity"];
export function FloorPlan(props: FloorPlanProps) { return <FloorPlanWorkspace key={props.venue.id} {...props}/>; }
function FloorPlanWorkspace({venue,data,act,compact=false,onOrder}:FloorPlanProps){
 const {contexts:serviceContexts,error:contextError}=useOrderServiceContexts(venue.id,data.orders);
 const {presence,error:presenceError}=useServicePresence(venue.id,data.orders);
 const now=useNow(30000);const [floor,setFloor]=useState(data.floors[0]?.id??"");const [room,setRoom]=useState(data.rooms.find(candidate=>candidate.floor_id===data.floors[0]?.id)?.id??"");const [selected,setSelected]=useState<Resource|null>(null);const [edit,setEdit]=useState<Resource|"new"|null>(null);const [addArea,setAddArea]=useState(false);
 const [editing,setEditing]=useState(false),[snap,setSnap]=useState(DEFAULT_FLOOR_SNAP),[profiles,setProfiles]=useState(false);
 const [overrides,setOverrides]=useState<Record<string,Resource>>({});
 const [optimistic,setOptimistic]=useState<{id:string;point:FloorPoint}|null>(null);
 const [positionNotice,setPositionNotice]=useState("");
 const [refreshing,setRefreshing]=useState(false);
 const mutation=useVenueMutation(venue.id,"flintplate:layout-pending:v1:",LAYOUT_PATHS,async()=>{
   const user=auth.getUser(),scope=JSON.stringify([user?.tenant_id,user?.sub]);
   setRefreshing(true);
   try {
     // Refresh only the resource versions. The global action banner would
     // shift the whole canvas underneath the pointer after every drop.
     const resources=await venueApi<Resource[]>(venue.id,"/tables");
     const current=auth.getUser();
     if(scope!==JSON.stringify([current?.tenant_id,current?.sub]))throw new Error("Bitte erneut persönlich anmelden.");
     setOverrides(Object.fromEntries(resources.map(resource=>[resource.id,resource])));
     setPositionNotice("Anordnung gespeichert.");
   }finally{setRefreshing(false);}
 });
 const locked=!mutation.ready||mutation.busy||!!mutation.pending||mutation.blocked;
 const displayed=data.resources.map(resource=>overrides[resource.id]&&overrides[resource.id].version>resource.version?overrides[resource.id]:resource);
 async function moveResource(resource:Resource,point:FloorPoint){
   if(locked)return;setPositionNotice("");setOptimistic({id:resource.id,point});
   if(!await mutation.send(`/tables/${resource.id}/position`,{version:resource.version,...point},`${resource.name} verschieben`))setPositionNotice("Die letzte bestätigte Position wird angezeigt. Ein unbestätigter Vorgang kann unten identisch geprüft werden.");
   setOptimistic(null);
 }
 async function retryLayout(){await mutation.retry();}
 const [editRoom,setEditRoom]=useState("");const [editKind,setEditKind]=useState("table");const [combinations,setCombinations]=useState<string[]>([]);
 const editArea=edit&&edit!=="new"&&(edit.room_id??"")===editRoom?edit.area:data.rooms.find(candidate=>candidate.id===editRoom)?.name??"Restaurant";
 const rooms=data.rooms.filter(r=>!floor||r.floor_id===floor);const resources=displayed.filter(r=>(!floor||rooms.some(a=>a.id===r.room_id))&&(!room||r.room_id===room));
 const current=selected?displayed.find(r=>r.id===selected.id)??selected:null;const usage=data.usage.find(u=>u.table_id===current?.id);
 function editResource(next:Resource|"new"){setEdit(next);setEditRoom(next==="new"?room:next.room_id??"");setEditKind(next==="new"?"table":next.kind);setCombinations(next==="new"?[]:next.combinable_with??[]);}
 async function save(event:React.FormEvent<HTMLFormElement>){event.preventDefault();if(locked)return;const f=new FormData(event.currentTarget);const target=edit!=="new"?edit:null;const body={name:str(f,"name"),kind:str(f,"kind"),tags:target?.tags??[],min_party:target?.min_party??1,combinable_with:editKind==="table"?combinations:[],room_id:str(f,"room")||null,area:editArea,seats:num(f,"seats"),hourly_rate_cents:Math.round(num(f,"rate")*100),billing_minutes:num(f,"billing"),tax_rate_bps:Math.round(num(f,"tax")*100),x:target?.x??100,y:target?.y??100,...(target?{version:target.version}:{})};if(await act(()=>venueApi(venue.id,target?`/tables/${target.id}`:"/tables",target?"PUT":"POST",body)))setEdit(null);}
 return <>
 <div className="fp-plan-controls">
   <Field label="Stockwerk"><select value={floor} onChange={e=>{setFloor(e.target.value);setRoom(data.rooms.find(candidate=>candidate.floor_id===e.target.value)?.id??"");}}><option value="">Alle Bereiche</option>{data.floors.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
   <Field label="Raumansicht"><select value={room} onChange={e=>setRoom(e.target.value)}><option value="">Alle Räume getrennt anzeigen</option>{rooms.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
   {!compact&&venue.role==="manager"&&<div className="fp-inline"><button className={`fp-button ${editing?"primary":""}`} aria-pressed={editing} disabled={locked} onClick={()=>setEditing(!editing)}><Move size={16}/>{editing?"Anordnung fertig":"Anordnung bearbeiten"}</button><button className="fp-button" onClick={()=>setProfiles(true)}><Layers size={16}/>Grundrissprofile</button><button className="fp-button" disabled={locked} onClick={()=>setAddArea(true)}><Plus size={16}/>Bereich</button><button className="fp-button" disabled={locked} onClick={()=>editResource("new")}><Plus size={16}/>Ressource</button></div>}
 </div>
 {editing&&<div className="fp-floor-edit-help"><p><Move size={16}/>Tisch ziehen und am sichtbaren Ziel loslassen. Antippen öffnet Details. Escape oder außerhalb loslassen verwirft das Ziehen.</p><label className="fp-check"><input type="checkbox" checked={snap} disabled={locked} onChange={e=>setSnap(e.target.checked)}/>Am Raster ausrichten</label><small>Mit Tastatur: Pfeiltasten verschieben · Umschalt für größere Schritte. Freie Fläche bleibt scrollbar.</small></div>}
 {(room?[{id:room,name:data.rooms.find(item=>item.id===room)?.name??"Raum"}]:[...rooms,...(!floor&&resources.some(item=>!item.room_id)?[{id:"",name:"Ohne Raumzuordnung"}]:[])]).map(board=><FloorCanvas key={board.id} label={board.name} compact={compact} editing={editing&&!compact} snap={snap} disabled={locked} selectedId={selected?.id} pendingId={optimistic?.id} onSelect={setSelected} onMove={moveResource} resources={resources.filter(resource=>(resource.room_id??"")===board.id).map(resource=>{
   const r=optimistic?.id===resource.id?{...resource,...optimistic.point}:resource;
   const open=data.orders.filter(order=>order.table_id===r.id&&usesOriginalTable(order,serviceContexts[order.id])&&!["settled","cancelled"].includes(order.status)).sort((a,b)=>a.created_at.localeCompare(b.created_at));
   const visitors=presence.find(value=>value.table_id===r.id);
   const running=data.usage.find(row=>row.table_id===r.id),bill=open.some(order=>order.pos_requested);
   const seated=data.reservations.find(row=>(row.table_ids??[row.table_id]).includes(r.id)&&row.status==="seated");
   const soon=data.reservations.find(row=>(row.table_ids??[row.table_id]).includes(r.id)&&row.status==="confirmed"&&new Date(row.ends_at).getTime()>now&&new Date(row.starts_at).getTime()-now<3600000);
   return {resource:r,state:bill?"bill":open.length||running||seated||visitors?.guest_count?"occupied":soon?"soon":"free",note:visitors?.guest_count?`${visitors.guest_count} Gäste · ${visitors.visit_ids.length} Besuche`:bill?"Zahlung angefordert":running?`In Nutzung ${since(running.starts_at,now)}`:open.length?`Belegt ${since(open[0].created_at,now)}`:seated?`Anwesend · ${seated.guest_name}`:soon?`Reserviert ${time(soon.starts_at,venue.timezone)}`:"Frei"};
 })}/>)}
 {!rooms.length&&!resources.length&&<Empty title="Hier entsteht dein Grundriss">Lege zuerst einen Bereich mit Raum an.</Empty>}
 <div className="fp-plan-legend"><span><i/>Frei</span><span><i className="soon"/>Reserviert</span><span><i className="occupied"/>Belegt</span><span><i className="bill"/>Zahlung angefordert</span></div>
 {(presenceError||contextError)&&<p className="fp-notice" role="status">{presenceError||contextError}</p>}
 {positionNotice&&<p className="fp-notice" role="status">{positionNotice}</p>}
 {refreshing&&<p className="fp-notice" role="status">Grundriss wird aktualisiert. Verschieben ist danach wieder möglich.</p>}
 {mutation.error&&<p className="fp-notice error" role="alert">{mutation.error}</p>}
 {mutation.pending&&<p className="fp-notice" role="status">{mutation.pending.label}: {mutation.busy?"Wird gespeichert …":"Bestätigung steht aus."}<button disabled={mutation.busy||mutation.blocked} onClick={()=>void retryLayout()}>Grundrissvorgang erneut prüfen</button></p>}
 {profiles&&<LayoutProfiles venue={venue} data={{...data,resources:displayed}} roomId={room||null} mutation={mutation} refreshing={refreshing} onClose={()=>setProfiles(false)}/>}
 {current&&<Modal title={current.name} onClose={()=>setSelected(null)}><Tag>{labels[current.kind]}</Tag><p className="fp-description"><MapPin size={16}/> {data.rooms.find(r=>r.id===current.room_id)?.name??current.area} · {current.seats} Personen</p>{current.kind!=="table"&&<><div className="fp-rate"><strong>{money(current.hourly_rate_cents)} / Stunde</strong><small>Abrechnung pro begonnenem {current.billing_minutes}-Minuten-Intervall.</small></div>{usage?<><p>In Nutzung seit {time(usage.starts_at,venue.timezone)} · {usage.guest_name}</p><button className="fp-button primary wide" onClick={async()=>{if(await act(()=>venueApi(venue.id,`/usage/${usage.id}/finish`,"POST"),"Nutzung beendet. Der Bon wartet auf Kassenübergabe."))setSelected(null);}}>Nutzung beenden & Bon anlegen</button></>:<form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);if(await act(()=>venueApi(venue.id,"/usage","POST",{request_key:newRequestId(),table_id:current.id,guest_name:str(f,"name"),duration_minutes:num(f,"duration")}),"Aktivität gestartet."))setSelected(null);}}><div className="fp-two"><Field label="Gast / Gruppe"><input name="name" required maxLength={120}/></Field><Field label="Geplante Minuten"><input name="duration" type="number" min={1} max={1440} defaultValue={60} required/></Field></div><button className="fp-button primary wide"><Clock3 size={17}/> Nutzung starten</button></form>}</>}<button className="fp-button wide" onClick={()=>{setSelected(null);onOrder(current.id);}}>Speisen & Getränke bestellen</button>{venue.role==="manager"&&<button className="fp-text-button" disabled={locked} onClick={()=>{editResource(current);setSelected(null);}}><Pencil size={15}/> Ressource bearbeiten</button>}</Modal>}{edit&&<Modal title={edit==="new"?"Neue Ressource":"Ressource bearbeiten"} onClose={()=>setEdit(null)}><form onSubmit={save}><Field label="Name"><input name="name" defaultValue={edit!=="new"?edit.name:""} required maxLength={40}/></Field><div className="fp-two"><Field label="Angebotsart"><select name="kind" value={editKind} onChange={e=>{setEditKind(e.target.value);setCombinations([]);}}>{categories.map(k=><option key={k} value={k}>{labels[k]}</option>)}</select></Field><Field label="Raum / Standort"><select name="room" value={editRoom} onChange={e=>{setEditRoom(e.target.value);setCombinations([]);}}><option value="">Ohne Raum</option>{data.rooms.map(r=><option key={r.id} value={r.id}>{data.floors.find(f=>f.id===r.floor_id)?.name} · {r.name}</option>)}</select></Field><Field label="Personenkapazität"><input name="seats" type="number" min={1} max={100} required defaultValue={edit!=="new"?edit.seats:4}/></Field><Field label="Stundentarif in €"><input name="rate" type="number" min={0} step="0.01" required defaultValue={edit!=="new"?edit.hourly_rate_cents/100:0}/></Field><Field label="Abrechnungstakt in Minuten"><input name="billing" type="number" min={1} max={60} required defaultValue={edit!=="new"?edit.billing_minutes:15}/></Field><Field label="Steuersatz in %"><input name="tax" type="number" min={0} max={100} step="0.01" required defaultValue={edit!=="new"?edit.tax_rate_bps/100:19}/></Field></div>{editKind==="table"&&<fieldset className="fp-fieldset"><legend>Kombinierbar mit</legend><p className="fp-description">Benachbarte Tische im selben Raum für gemeinsame Reservierungen verbinden.</p><div className="fp-booking-tables">{data.resources.filter(r=>r.kind==="table"&&r.id!==(edit!=="new"?edit.id:"")&&r.room_id===(editRoom||null)&&r.area===editArea).map(r=><label className="fp-check" key={r.id}><input type="checkbox" checked={combinations.includes(r.id)} disabled={combinations.length>=8&&!combinations.includes(r.id)} onChange={e=>setCombinations(previous=>e.target.checked?[...previous,r.id]:previous.filter(id=>id!==r.id))}/> {r.name} · {r.seats} Plätze</label>)}</div></fieldset>}<button className="fp-button primary wide">Speichern</button></form></Modal>}{addArea&&<Modal title="Stockwerk & Raum anlegen" onClose={()=>setAddArea(false)}><form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);await act(()=>venueApi(venue.id,"/floors","POST",{name:str(f,"name"),level:num(f,"level")}));}}><div className="fp-two"><Field label="Stockwerk / Außenbereich"><input name="name" required placeholder="Am See" maxLength={80}/></Field><Field label="Ebene"><input name="level" type="number" min={-10} max={100} defaultValue={0} required/></Field></div><button className="fp-button">Stockwerk anlegen</button></form><hr/><form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);if(await act(()=>venueApi(venue.id,"/rooms","POST",{name:str(f,"name"),floor_id:str(f,"floor")})))setAddArea(false);}}><Field label="Stockwerk"><select name="floor" required>{data.floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></Field><Field label="Raum / Standort"><input name="name" required placeholder="Bootssteg" maxLength={80}/></Field><button className="fp-button primary wide">Raum anlegen</button></form></Modal>}</>;
}
