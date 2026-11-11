"use client";
import { useCallback, useEffect, useState } from "react";
import { BookUser, Cake, Download, EyeOff, Lock, Search, ShieldAlert, Trash2, Users } from "lucide-react";
import { date, day, message, str, venueApi, type DietMarker, type GuestNote, type GuestProfile, type GuestProfileDetail, type Venue } from "@/lib/flintplate";
import { Empty, Field, Modal, Tag } from "./shared";


const CATEGORIES:[string,string][] = [
 ["vorliebe","Vorliebe"],
 ["anlass","Anlass"],
 ["gespraech","Gespräch"],
 ["hinweis","Hinweis für den Service"],
 ["gesundheit","Gesundheit"],
 ["ernaehrung","Ernährung"],
];
const SPECIAL=["gesundheit","ernaehrung"];
const name=(key:string)=>CATEGORIES.find(([id])=>id===key)?.[1]??key;

/** Remembering guests is allowed; forgetting them has to be just as easy. */
export function GuestBook({venue}:{venue:Venue}){
 const [rows,setRows]=useState<GuestProfile[]>([]);
 const [query,setQuery]=useState("");
 const [open,setOpen]=useState<GuestProfileDetail|null>(null);
 const [add,setAdd]=useState(false);
 const [markers,setMarkers]=useState<DietMarker[]>([]);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");

 const reload=useCallback(async(term=query)=>{
  setRows(await venueApi<GuestProfile[]>(venue.id,`/guestbook?query=${encodeURIComponent(term)}`));
 },[venue.id,query]);
 useEffect(()=>{reload("").catch(e=>setError(message(e)));},[reload]);
 useEffect(()=>{venueApi<DietMarker[]>(venue.id,"/diet-markers").then(setMarkers).catch(()=>undefined);},[venue.id]);

 async function run(work:()=>Promise<unknown>,success:string){
  setBusy(true);setError("");setNotice("");
  try{await work();await reload();setNotice(success);return true;}
  catch(e){setError(message(e));return false;}
  finally{setBusy(false);}
 }
 async function show(id:string){
  setBusy(true);setError("");
  try{setOpen(await venueApi<GuestProfileDetail>(venue.id,`/guestbook/${id}`));}
  catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 return <section className="fp-panel">
  <div className="fp-section-head">
   <div><h2>Kundenbuch</h2><p>Stammgäste wiedererkennen, ohne ein Archiv über Menschen anzulegen.</p></div>
   <button className="fp-button primary" onClick={()=>setAdd(true)}><BookUser size={17}/> Gast aufnehmen</button>
  </div>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  {notice&&<p className="fp-notice" role="status">{notice}</p>}

  <form className="fp-search" onSubmit={e=>{e.preventDefault();void reload();}}>
   <Search size={18}/>
   <input aria-label="Gast suchen" placeholder="Name oder Merkhilfe suchen …" value={query} onChange={e=>setQuery(e.target.value)}/>
  </form>

  <div className="fp-guest-list">
   {rows.map(row=><button className="fp-guest-card" key={row.id} onClick={()=>void show(row.id)}>
    <span className="fp-person">{row.display_name.split(" ").map(part=>part[0]).slice(0,2).join("")}</span>
    <span className="fp-guest-body">
     <strong>{row.display_name}</strong>
     <small>{row.reference||"Ohne Merkhilfe"}</small>
     <span className="fp-inline wrap">
      <Tag>{row.notes} {row.notes===1?"Notiz":"Notizen"}</Tag>
      {row.birthday&&<Tag><Cake size={12}/> {row.birthday}</Tag>}
      {row.consent_special&&<Tag tone="green">Einwilligung</Tag>}
     </span>
    </span>
   </button>)}
  </div>
  {!rows.length&&<Empty title="Noch niemand im Kundenbuch">Nimm Stammgäste auf, die dein Team wiedererkennen soll. Jede Notiz läuft nach {venue.guestbook_retention_days??365} Tagen von selbst ab.</Empty>}

  {add&&<Modal title="Gast aufnehmen" onClose={()=>setAdd(false)}>
   <form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);if(await run(()=>venueApi(venue.id,"/guestbook","POST",{display_name:str(f,"name"),reference:str(f,"reference"),birthday:str(f,"birthday")||null}),"Gast aufgenommen."))setAdd(false);}}>
    <Field label="Name oder Ansprache"><input name="name" required minLength={2} maxLength={120} placeholder="Familie Sommer"/></Field>
    <Field label="Merkhilfe für das Team"><input name="reference" maxLength={160} placeholder="Stammtisch Freitag, sitzt hinten links"/></Field>
    <Field label="Geburtstag als TT.MM (freiwillig)"><input name="birthday" maxLength={5} placeholder="04.05" pattern="\d{2}\.\d{2}"/></Field>
    <p className="fp-hint"><ShieldAlert size={14}/> Kein Geburtsjahr, keine Adresse, keine Telefonnummer. Es geht ums Wiedererkennen, nicht ums Sammeln.</p>
    <button className="fp-button primary wide" disabled={busy}>Aufnehmen</button>
   </form>
  </Modal>}

  {open&&<Modal title={open.display_name} onClose={()=>setOpen(null)}>
   <p className="fp-description">{open.reference||"Ohne Merkhilfe"}{open.birthday?` · Geburtstag ${open.birthday}`:""}</p>

   <div className="fp-consent">
    <div>
     <strong>Gesundheit und Ernährung</strong>
     <small>{open.consent_special?`Einwilligung festgehalten${open.consent_at?` am ${date(open.consent_at,venue.timezone)}`:""}.`:"Ohne ausdrückliche Einwilligung des Gastes lassen sich solche Hinweise nicht speichern."}</small>
    </div>
    <button className="fp-button" disabled={busy} onClick={async()=>{
     const granted=!open.consent_special;
     if(!granted&&!window.confirm("Widerruf löscht alle Hinweise zu Gesundheit und Ernährung dieser Person. Fortfahren?"))return;
     setBusy(true);setError("");
     try{await venueApi(venue.id,`/guestbook/${open.id}/consent`,"PUT",{version:open.version,granted});await show(open.id);await reload();setNotice(granted?"Einwilligung festgehalten.":"Einwilligung widerrufen, betroffene Hinweise gelöscht.");}
     catch(err){setError(message(err));}
     finally{setBusy(false);}
    }}>{open.consent_special?"Einwilligung widerrufen":"Einwilligung festhalten"}</button>
   </div>

   <form onSubmit={async e=>{e.preventDefault();const form=e.currentTarget;const f=new FormData(form);setBusy(true);setError("");
    try{await venueApi(venue.id,`/guestbook/${open.id}/notes`,"POST",{text:str(f,"text"),category:str(f,"category"),visibility:str(f,"visibility")});form.reset();await show(open.id);await reload();setNotice("Notiz gespeichert.");}
    catch(err){setError(message(err));}
    finally{setBusy(false);}}}>
    <Field label="Was soll das Team wissen?"><textarea name="text" required minLength={2} maxLength={1000} rows={2} placeholder="Erzählt gern von seiner Zeit in Hamburg."/></Field>
    <div className="fp-two">
     <Field label="Art"><select name="category" defaultValue="vorliebe">{CATEGORIES.map(([id,text])=><option key={id} value={id}>{text}{SPECIAL.includes(id)?" · braucht Einwilligung":""}</option>)}</select></Field>
     <Field label="Sichtbar für"><select name="visibility" defaultValue="team"><option value="team">Das ganze Serviceteam</option><option value="private">Nur für mich</option></select></Field>
    </div>
    <button className="fp-button primary wide" disabled={busy}>Notiz hinzufügen</button>
   </form>

   <h3 className="fp-subhead">Merkmale</h3>
   {markers.length?<div className="fp-chipset" role="group" aria-label="Merkmale dieses Gastes">{markers.filter(row=>row.active).map(row=>{
    const active=(open.markers??[]).includes(row.key);
    return <button type="button" className={`fp-chip-button ${active?"active":""}`} key={row.key} aria-pressed={active} disabled={busy} title={row.special?"Braucht die Einwilligung des Gastes":row.note} onClick={async()=>{
     const next=active?(open.markers??[]).filter(key=>key!==row.key):[...(open.markers??[]),row.key];
     setBusy(true);setError("");
     try{await venueApi(venue.id,`/guestbook/${open.id}/markers`,"PUT",{version:open.version,markers:next});await show(open.id);setNotice("Merkmale gespeichert.");}
     catch(err){setError(message(err));}
     finally{setBusy(false);}
    }}>{row.label}{row.legal_block?" · Sperre":row.special?" *":""}</button>;
   })}</div>:<p className="fp-hint">Noch keine Merkmale angelegt. Unter „Merkmale und Sperren“ lassen sich die üblichen übernehmen.</p>}
   <p className="fp-hint">Mit * markierte Merkmale berühren Gesundheit, Schwangerschaft oder Glauben und brauchen die Einwilligung oben. Eine Sperre verhindert die Bestellung wirklich, alles andere warnt und kann bestätigt werden.</p>

   <h3 className="fp-subhead">Notizen</h3>
   {open.entries.map(entry=><NoteRow key={entry.id} entry={entry} venue={venue} busy={busy} onDelete={async()=>{
    if(!window.confirm("Diese Notiz löschen?"))return;
    setBusy(true);setError("");
    try{await venueApi(venue.id,`/guestbook/${open.id}/notes/${entry.id}`,"DELETE");await show(open.id);await reload();setNotice("Notiz gelöscht.");}
    catch(err){setError(message(err));}
    finally{setBusy(false);}
   }}/>)}
   {!open.entries.length&&<Empty title="Noch nichts notiert">Die erste Notiz hilft dem nächsten Dienst.</Empty>}

   <p className="fp-hint"><EyeOff size={14}/> „Nur für mich“ heißt: andere im Team sehen es nicht. Es bleibt trotzdem eine Notiz des Betriebs. Der Gast kann Auskunft verlangen, dann steht sie in der Auskunft, und die Leitung kann sie löschen.</p>
   <p className="fp-hint"><ShieldAlert size={14}/> Jedes Öffnen dieses Eintrags steht im Betriebsjournal. Notizen laufen nach {open.retention_days} Tagen ab und werden dann entfernt.</p>

   {venue.role==="manager"&&<div className="fp-inline">
    <button className="fp-button" disabled={busy} onClick={async()=>{
     setBusy(true);setError("");
     try{
      const data=await venueApi<unknown>(venue.id,`/guestbook/${open.id}/export`);
      const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
      const url=URL.createObjectURL(blob);const link=document.createElement("a");
      link.href=url;link.download=`auskunft-${open.display_name.replace(/\s+/g,"-").toLowerCase()}.json`;link.click();
      URL.revokeObjectURL(url);setNotice("Auskunft heruntergeladen.");
     }catch(err){setError(message(err));}
     finally{setBusy(false);}
    }}><Download size={15}/> Auskunft erzeugen</button>
    <button className="fp-text-button" disabled={busy} onClick={async()=>{
     if(!window.confirm(`${open.display_name} mit allen Notizen endgültig löschen?`))return;
     if(await run(()=>venueApi(venue.id,`/guestbook/${open.id}`,"DELETE"),"Person vollständig gelöscht."))setOpen(null);
    }}><Trash2 size={15}/> Person löschen</button>
   </div>}
  </Modal>}
 </section>;
}

function NoteRow({entry,venue,busy,onDelete}:{entry:GuestNote;venue:Venue;busy:boolean;onDelete:()=>void}){
 return <article className="fp-note">
  <div className="fp-inline wrap">
   <Tag tone={entry.sensitive?"amber":"neutral"}>{name(entry.category)}</Tag>
   <Tag>{entry.visibility==="private"?<><Lock size={12}/> Nur für mich</>:<><Users size={12}/> Team</>}</Tag>
   <small>{entry.author_name} · {date(entry.created_at,venue.timezone)}</small>
  </div>
  <p>{entry.text}</p>
  <div className="fp-inline">
   <small>Läuft ab am {date(entry.expires_at,venue.timezone)}</small>
   {(entry.mine||venue.role==="manager")&&<button className="fp-text-button" disabled={busy} onClick={onDelete}>Löschen</button>}
  </div>
 </article>;
}
