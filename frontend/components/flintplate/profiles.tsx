"use client";
import { useCallback, useEffect, useState } from "react";
import { Copy, Layers, Link2Off, Pencil, Plus, TriangleAlert } from "lucide-react";
import { labels, message, num, str, venueApi, type ProfileImpact, type ProfileTemplate, type StaffProfile, type Station, type Venue } from "@/lib/flintplate";
import { Empty, Field, Modal, Tag } from "./shared";

const STATIONS:Station[]=["service","kitchen","bar","activities"];
const STATION_LABEL:Record<Station,string>={service:"Service",kitchen:"Küche",bar:"Bar",activities:"Aktivitäten"};
const LEVEL=["","Einarbeitung","Grundlagen","Sicher","Erfahren","Führt an"];
type TemplateValues={name:string;description:string;stations:Station[];competence:number;active:boolean};

/** Qualification travels through templates; role and voluntary standby never do. */
export function ProfileTemplates({venue}:{venue:Venue}){
 const [templates,setTemplates]=useState<ProfileTemplate[]>([]);
 const [people,setPeople]=useState<StaffProfile[]>([]);
 const [edit,setEdit]=useState<ProfileTemplate|"new"|null>(null);
 const [copyTo,setCopyTo]=useState<StaffProfile|null>(null);
 const [impact,setImpact]=useState<{values:TemplateValues;preview:ProfileImpact;target:ProfileTemplate}|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");

 const reload=useCallback(async()=>{
  const [list,staff]=await Promise.all([
   venueApi<ProfileTemplate[]>(venue.id,"/profile-templates"),
   venueApi<StaffProfile[]>(venue.id,"/staff-profiles"),
  ]);
  setTemplates(list);setPeople(staff);
 },[venue.id]);
 useEffect(()=>{reload().catch(e=>setError(message(e)));},[reload]);

 async function run(work:()=>Promise<unknown>,success:string){
  setBusy(true);setError("");setNotice("");
  try{await work();await reload();setNotice(success);return true;}
  catch(e){setError(message(e));return false;}
  finally{setBusy(false);}
 }

 function read(form:FormData):TemplateValues{
  return {name:str(form,"name"),description:str(form,"description"),stations:form.getAll("station").map(String) as Station[],competence:num(form,"competence"),active:true};
 }

 async function submitTemplate(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  const values=read(new FormData(event.currentTarget));
  if(edit==="new"){if(await run(()=>venueApi(venue.id,"/profile-templates","POST",values),"Vorlage angelegt."))setEdit(null);return;}
  if(!edit)return;
  setBusy(true);setError("");
  try{
   const preview=await venueApi<ProfileImpact>(venue.id,`/profile-templates/${edit.id}/impact`,"POST",values);
   if(!preview.changes.length){if(await run(()=>venueApi(venue.id,`/profile-templates/${edit.id}`,"PUT",{...values,version:edit.version}),"Vorlage gespeichert."))setEdit(null);return;}
   setImpact({values,preview,target:edit});setEdit(null);
  }catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 async function confirmImpact(){
  if(!impact)return;
  const {values,target}=impact;
  if(await run(()=>venueApi(venue.id,`/profile-templates/${target.id}`,"PUT",{...values,version:target.version}),`Vorlage übernommen für ${impact.preview.affected_members} Personen.`))setImpact(null);
 }

 const assign=(person:StaffProfile,body:Record<string,unknown>,success:string)=>run(()=>venueApi(venue.id,`/staff-profiles/${person.worker_id}`,"PUT",body),success);

 return <section className="fp-panel">
  <div className="fp-section-head">
   <div><h2>Profile und Vorlagen</h2><p>Eine Vorlage pflegen statt dreißig Profile. Wer eigene Werte braucht, behält sie sichtbar.</p></div>
   <button className="fp-button primary" onClick={()=>setEdit("new")}><Plus size={17}/> Vorlage</button>
  </div>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  {notice&&<p className="fp-notice" role="status">{notice}</p>}

  <div className="fp-template-grid">
   {templates.map(t=><article className="fp-template" key={t.id}>
    <header><strong>{t.name}</strong><Tag tone={t.members?"green":"neutral"}>{t.members} {t.members===1?"Person":"Personen"}</Tag></header>
    {t.description&&<p>{t.description}</p>}
    <div className="fp-inline wrap">{t.stations.map(s=><Tag key={s}>{STATION_LABEL[s]}</Tag>)}{!t.stations.length&&<small>Ohne Station</small>}</div>
    <small>Erfahrung: {LEVEL[t.competence]}</small>
    <div className="fp-inline">
     <button className="fp-text-button" onClick={()=>setEdit(t)}><Pencil size={14}/> Bearbeiten</button>
     {!t.members&&<button className="fp-text-button" disabled={busy} onClick={()=>void run(()=>venueApi(venue.id,`/profile-templates/${t.id}`,"DELETE"),"Vorlage entfernt.")}>Entfernen</button>}
    </div>
   </article>)}
   {!templates.length&&<Empty title="Noch keine Vorlage">Lege an, was sich bei mehreren Personen wiederholt, etwa „Service erfahren“ oder „Küche Einarbeitung“.</Empty>}
  </div>

  <div className="fp-table-wrap">
   <table>
    <thead><tr><th>Person</th><th>Vorlage</th><th>Stationen</th><th>Erfahrung</th><th>Aktion</th></tr></thead>
    <tbody>{people.map(p=><tr key={p.worker_id}>
     <td><strong>{p.full_name}</strong><small>{labels[p.role]??p.role}</small></td>
     <td>
      <select aria-label={`Vorlage für ${p.full_name}`} value={p.template_id??""} disabled={busy}
       onChange={e=>void assign(p,{template_id:e.target.value||null,overrides:[]},e.target.value?"Vorlage zugewiesen.":"Vorlage gelöst, die zuletzt geerbten Werte bleiben.")}>
       <option value="">Ohne Vorlage</option>
       {templates.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
     </td>
     <td><div className="fp-origin"><span>{p.stations.map(s=>STATION_LABEL[s]).join(", ")||"—"}</span><Origin person={p} field="stations" busy={busy} assign={assign}/></div></td>
     <td><div className="fp-origin"><span>{LEVEL[p.competence]}</span><Origin person={p} field="competence" busy={busy} assign={assign}/></div></td>
     <td><button className="fp-text-button" onClick={()=>setCopyTo(p)}><Copy size={14}/> Von Person übernehmen</button></td>
    </tr>)}</tbody>
   </table>
  </div>
  {!people.length&&<Empty title="Noch niemand zugeordnet">Berechtige Personen aus dem FlintPlate-Personalstamm für diese Betriebsstätte.</Empty>}

  {edit&&<Modal title={edit==="new"?"Neue Vorlage":"Vorlage bearbeiten"} onClose={()=>setEdit(null)}>
   <form onSubmit={submitTemplate}>
    <Field label="Name"><input name="name" required maxLength={80} defaultValue={edit==="new"?"":edit.name} placeholder="Service erfahren"/></Field>
    <Field label="Wofür steht diese Vorlage?"><input name="description" maxLength={300} defaultValue={edit==="new"?"":edit.description} placeholder="Getränke, Gastkontakt, Einarbeitung neuer Kräfte."/></Field>
    <fieldset className="fp-chipset"><legend>Stationen</legend>{STATIONS.map(s=><label className="fp-chip" key={s}><input type="checkbox" name="station" value={s} defaultChecked={edit!=="new"&&edit.stations.includes(s)}/> {STATION_LABEL[s]}</label>)}</fieldset>
    <Field label="Erfahrungsstufe"><select name="competence" defaultValue={edit==="new"?3:edit.competence}>{[1,2,3,4,5].map(v=><option key={v} value={v}>{v} · {LEVEL[v]}</option>)}</select></Field>
    <p className="fp-hint"><TriangleAlert size={14}/> Rolle und freiwillige Vertretungsbereitschaft gehören der Person und werden nie über eine Vorlage gesetzt.</p>
    <button className="fp-button primary wide" disabled={busy}>{edit==="new"?"Vorlage anlegen":"Änderung prüfen"}</button>
   </form>
  </Modal>}

  {impact&&<Modal title="Das ändert sich" onClose={()=>setImpact(null)}>
   <p className="fp-description">{impact.preview.changes.length} {impact.preview.changes.length===1?"Änderung":"Änderungen"} bei {impact.preview.affected_members} {impact.preview.affected_members===1?"Person":"Personen"}. Nichts ist bisher gespeichert.</p>
   <ul className="fp-change-list">{impact.preview.changes.map((c,i)=><li key={i}><strong>{c.full_name}</strong><span>{c.field==="stations"?"Stationen":"Erfahrung"}: {display(c.field,c.before)} → {display(c.field,c.after)}</span></li>)}</ul>
   {!!impact.preview.shielded.length&&<p className="fp-hint"><Link2Off size={14}/> Unverändert wegen eigener Werte: {impact.preview.shielded.map(s=>s.full_name).join(", ")}.</p>}
   <div className="fp-inline">
    <button className="fp-button" onClick={()=>setImpact(null)}>Abbrechen</button>
    <button className="fp-button primary" disabled={busy} onClick={()=>void confirmImpact()}>Übernehmen</button>
   </div>
  </Modal>}

  {copyTo&&<Modal title={`Einstellungen für ${copyTo.full_name} übernehmen`} onClose={()=>setCopyTo(null)}>
   <p className="fp-description"><Layers size={16}/> Stationen, Erfahrung und die Vorlagenbindung werden übernommen. Rolle und freiwillige Bereitschaft bleiben unverändert.</p>
   <form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);if(await run(()=>venueApi(venue.id,`/staff-profiles/${copyTo.worker_id}/copy-from`,"POST",{source_worker_id:str(f,"source")}),"Einstellungen übernommen."))setCopyTo(null);}}>
    <Field label="Von welcher Person?"><select name="source" required>{people.filter(p=>p.worker_id!==copyTo.worker_id).map(p=><option key={p.worker_id} value={p.worker_id}>{p.full_name} · {p.template_name||"ohne Vorlage"}</option>)}</select></Field>
    <button className="fp-button primary wide" disabled={busy}>Übernehmen</button>
   </form>
  </Modal>}
 </section>;
}

function Origin({person,field,busy,assign}:{person:StaffProfile;field:"stations"|"competence";busy:boolean;assign:(p:StaffProfile,body:Record<string,unknown>,success:string)=>Promise<boolean>}){
 const source=field==="stations"?person.stations_source:person.competence_source;
 if(!person.template_id) return <small>eigener Wert</small>;
 const others=(person.stations_source==="eigen"?["stations"]:[]).concat(person.competence_source==="eigen"?["competence"]:[]).filter(f=>f!==field);
 if(source==="Vorlage") return <button className="fp-text-button" disabled={busy} title="Wert von der Vorlage lösen" onClick={()=>void assign(person,{template_id:person.template_id,overrides:[...others,field]},"Feld wird jetzt eigenständig gepflegt.")}><Tag>geerbt</Tag></button>;
 return <button className="fp-text-button" disabled={busy} title="Wieder von der Vorlage übernehmen" onClick={()=>void assign(person,{template_id:person.template_id,overrides:others},"Feld folgt wieder der Vorlage.")}><Tag tone="amber">eigen</Tag></button>;
}

function display(field:"stations"|"competence",value:unknown):string{
 if(field==="competence") return LEVEL[Number(value)]??String(value);
 const list=Array.isArray(value)?value as Station[]:[];
 return list.map(s=>STATION_LABEL[s]).join(", ")||"—";
}
