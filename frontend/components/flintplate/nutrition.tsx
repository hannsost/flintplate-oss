"use client";
import { useCallback, useEffect, useState } from "react";
import { Info, ShieldAlert, TriangleAlert } from "lucide-react";
import { message, venueApi, type DietMarker, type ItemDetail, type Venue } from "@/lib/flintplate";
import { Field, Modal, Tag } from "./shared";

export const KIND:Record<string,string>={allergie:"Allergie",diaet:"Diät",zustand:"Zustand"};

/** The ingredient list the service reads out when a guest asks at the table. */
export function DishDetails({venueId,itemId,onClose}:{venueId:string;itemId:string;onClose:()=>void}){
 const [detail,setDetail]=useState<ItemDetail|null>(null);
 const [error,setError]=useState("");
 useEffect(()=>{venueApi<ItemDetail>(venueId,`/menu/${itemId}/details`).then(setDetail).catch(e=>setError(message(e)));},[venueId,itemId]);
 return <Modal title={detail?.name??"Zutaten"} onClose={onClose}>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  {!detail?<p>Wird geladen …</p>:<>
   <p className="fp-description">{detail.description||"Ohne Beschreibung"}</p>
   <div className="fp-inline wrap">
    <Tag>{detail.category}</Tag>
    <Tag>{detail.station==="bar"?"Bar":"Küche"}</Tag>
    {!detail.published&&<Tag tone="amber">Nur Entwurf</Tag>}
    {!detail.available&&<Tag tone="amber">Nicht verfügbar</Tag>}
   </div>
   <h3 className="fp-subhead">Zutaten</h3>
   {detail.ingredients.length?<ul className="fp-ingredients">{detail.ingredients.map(row=><li key={row.name}>
    <span><strong>{row.name}</strong>{row.note&&<small> · {row.note}</small>}</span>
    {!!row.allergens.length&&<Tag tone="amber">{row.allergens.join(", ")}</Tag>}
   </li>)}</ul>:<p className="fp-hint"><Info size={14}/> Für dieses Gericht ist noch keine Zutatenliste hinterlegt. Bitte in der Küche nachfragen und sie unter Karte &amp; Preise ergänzen.</p>}
   <h3 className="fp-subhead">Kennzeichnung</h3>
   <p>Allergene: {detail.allergens.join(", ")||"keine angegeben"}</p>
   <p>Enthält: {detail.contains.join(", ")||"nichts hinterlegt"}</p>
   <p className="fp-hint"><ShieldAlert size={14}/> Diese Angaben stammen aus der Karte des Betriebs. Bei einer ernsten Allergie immer in der Küche rückfragen.</p>
  </>}
 </Modal>;
}

/** Markers a venue reacts to. A new diet is a new row here, not new code. */
export function DietMarkers({venue}:{venue:Venue}){
 const [rows,setRows]=useState<DietMarker[]>([]);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");
 const [add,setAdd]=useState(false);

 const load=useCallback(async()=>{setRows(await venueApi<DietMarker[]>(venue.id,"/diet-markers"));},[venue.id]);
 useEffect(()=>{load().catch(e=>setError(message(e)));},[load]);

 async function run(work:()=>Promise<unknown>,success:string){
  setBusy(true);setError("");setNotice("");
  try{await work();await load();setNotice(success);return true;}
  catch(e){setError(message(e));return false;}
  finally{setBusy(false);}
 }

 return <section className="fp-panel">
  <div className="fp-section-head">
   <div><h2>Merkmale und Sperren</h2><p>Woran sich der Betrieb bei einem Gast orientiert und welche Zutaten das ausschließt.</p></div>
   <div className="fp-inline">
    {!rows.length&&<button className="fp-button" disabled={busy} onClick={()=>void run(()=>venueApi(venue.id,"/diet-markers/defaults","POST"),"Übliche Merkmale übernommen.")}>Übliche übernehmen</button>}
    <button className="fp-button primary" onClick={()=>setAdd(true)}>Eigenes Merkmal</button>
   </div>
  </div>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  {notice&&<p className="fp-notice" role="status">{notice}</p>}
  <div className="fp-marker-grid">
   {rows.map(row=><article className="fp-marker" key={row.id}>
    <header><strong>{row.label}</strong>{row.legal_block?<Tag tone="amber">gesetzliche Sperre</Tag>:<Tag>Warnung</Tag>}</header>
    <small>{KIND[row.kind]}{row.special?" · einwilligungspflichtig":""}</small>
    <p>Schließt aus: {row.avoid.join(", ")||"nichts"}</p>
    {row.note&&<small>{row.note}</small>}
   </article>)}
  </div>
  {!rows.length&&<p className="fp-hint"><Info size={14}/> Noch keine Merkmale. „Übliche übernehmen“ legt einen Startsatz an, den du danach frei änderst.</p>}
  <p className="fp-hint"><TriangleAlert size={14}/> Nur eine gesetzliche Sperre verhindert eine Bestellung wirklich, aktuell Alkohol bei Minderjährigen. Alles andere warnt sichtbar und lässt sich von einem Menschen bestätigen, damit eine veraltete Angabe niemanden aussperrt.</p>

  {add&&<Modal title="Eigenes Merkmal" onClose={()=>setAdd(false)}>
   <form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);
    const payload={key:String(f.get("key")).trim().toLowerCase(),label:String(f.get("label")),kind:String(f.get("kind")),special:f.get("special")==="on",legal_block:false,avoid:String(f.get("avoid")).split(",").map(part=>part.trim()).filter(Boolean),note:String(f.get("note"))};
    if(await run(()=>venueApi(venue.id,"/diet-markers","POST",payload),"Merkmal angelegt."))setAdd(false);}}>
    <div className="fp-two">
     <Field label="Schlüssel"><input name="key" required pattern="[a-z0-9_-]{2,40}" placeholder="pescetarisch"/></Field>
     <Field label="Bezeichnung"><input name="label" required maxLength={80} placeholder="Pescetarisch"/></Field>
    </div>
    <Field label="Art"><select name="kind" defaultValue="diaet"><option value="diaet">Diät</option><option value="allergie">Allergie</option><option value="zustand">Zustand</option></select></Field>
    <Field label="Schließt diese Zutaten aus, mit Komma getrennt"><input name="avoid" placeholder="fleisch, gefluegel"/></Field>
    <Field label="Hinweis für das Team"><input name="note" maxLength={300}/></Field>
    <label className="fp-check"><input type="checkbox" name="special"/> Berührt Gesundheit, Schwangerschaft oder Glauben und braucht die Einwilligung des Gastes</label>
    <button className="fp-button primary wide" disabled={busy}>Anlegen</button>
   </form>
  </Modal>}
 </section>;
}
