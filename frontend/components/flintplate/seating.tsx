"use client";
import { useState } from "react";
import { CircleCheck, Sparkles, TriangleAlert, Wand2 } from "lucide-react";
import { message, num, str, time, toISO, venueApi, type Proposal, type ProposalOption, type Resource, type Venue } from "@/lib/flintplate";
import { Field, Tag } from "./shared";

/** Three explained options for one reservation. The proposal books nothing by itself. */
export function SeatingAssistant({venue,resources,onBooked}:{venue:Venue;resources:Resource[];onBooked:(message:string)=>void}){
 const [proposal,setProposal]=useState<Proposal|null>(null);
 const [chosen,setChosen]=useState<string>("");
 const [guests,setGuests]=useState(2);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const tags=[...new Set(resources.flatMap(r=>r.tags))].sort();
 const areas=[...new Set(resources.map(r=>r.area))].sort();

 async function ask(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  const f=new FormData(event.currentTarget);
  setBusy(true);setError("");
  try{
   const result=await venueApi<Proposal>(venue.id,"/reservations/propose","POST",{
    starts_at:toISO(f.get("start")),
    ends_at:f.get("end")?toISO(f.get("end")):null,
    guests:num(f,"guests"),
    kind:str(f,"kind")||"table",
    prefer_area:str(f,"area"),
    prefer_tags:f.getAll("tag").map(String),
    prompt:str(f,"prompt"),
   });
   setGuests(num(f,"guests"));
   setProposal(result);
   setChosen(result.options[0]?.key??"");
  }catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 async function book(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  if(!proposal||!chosen)return;
  const f=new FormData(event.currentTarget);
  setBusy(true);setError("");
  try{
   await venueApi(venue.id,`/decisions/${proposal.decision_id}/accept`,"POST",{version:1,option_key:chosen,guest_name:str(f,"name")});
   onBooked("Vorschlag angenommen und verbindlich reserviert.");
  }catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 if(!proposal) return <form onSubmit={ask}>
  <p className="fp-description"><Sparkles size={16}/> Wir prüfen freie Ressourcen, Sitzplätze, kombinierbare Nachbarn und den Rückhalt für Laufkundschaft und schlagen drei Wege vor.</p>
  <div className="fp-two">
   <Field label="Beginn (Gerätezeit)"><input name="start" type="datetime-local" required/></Field>
   <Field label="Ende (optional)"><input name="end" type="datetime-local"/></Field>
  </div>
  <div className="fp-two">
   <Field label="Personen"><input name="guests" type="number" min={1} max={100} defaultValue={2} required/></Field>
   <Field label="Angebotsart"><select name="kind" defaultValue="table"><option value="table">Tisch</option><option value="bowling">Bowling</option><option value="billiard">Billard</option><option value="pedal_boat">Tretboot</option><option value="activity">Weiteres Angebot</option></select></Field>
  </div>
  <Field label="Bevorzugter Bereich"><select name="area" defaultValue=""><option value="">Ohne Vorgabe</option>{areas.map(a=><option key={a} value={a}>{a}</option>)}</select></Field>
  {!!tags.length&&<fieldset className="fp-chipset"><legend>Gewünschte Merkmale</legend>{tags.map(tag=><label className="fp-chip" key={tag}><input type="checkbox" name="tag" value={tag}/> {tag}</label>)}</fieldset>}
  <Field label="Zusätzliche Punkte für die Entscheidung"><textarea name="prompt" rows={2} maxLength={1000} placeholder="Zum Beispiel: heute Abend viel Laufkundschaft erwartet, große Runden zusammenhalten."/></Field>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  <button className="fp-button primary wide" disabled={busy}><Wand2 size={17}/> Drei Vorschläge zeigen</button>
 </form>;

 return <form onSubmit={book}>
  {proposal.notes.map(note=><p className="fp-notice" key={note} role="status">{note}</p>)}
  {!!proposal.prompt_note&&<p className="fp-description">{proposal.prompt_applied?<CircleCheck size={16}/>:<TriangleAlert size={16}/>} {proposal.prompt_note}</p>}
  {!proposal.options.length&&<p className="fp-notice error" role="alert">Für diese Angaben wurde keine passende Ressource gefunden. Andere Zeit, kleinere Gruppe oder anderes Angebot versuchen.</p>}
  <div className="fp-options" role="radiogroup" aria-label="Vorschläge">
   {proposal.options.map(option=><OptionCard key={option.key} option={option} venue={venue} selected={chosen===option.key} onSelect={()=>setChosen(option.key)}/>)}
  </div>
  {!!proposal.options.length&&<>
   <Field label="Name des Gastes / der Gruppe"><input name="name" required maxLength={120}/></Field>
   <p className="fp-hint">{guests} Personen · Vorschlag {proposal.engine==="rules"?"regelbasiert":"regelbasiert mit Modellgewichtung"} · {proposal.considered} Möglichkeiten geprüft</p>
  </>}
  {error&&<p className="fp-notice error" role="alert">{error}</p>}
  <div className="fp-inline">
   <button type="button" className="fp-button" onClick={()=>{setProposal(null);setError("");}}>Angaben ändern</button>
   {!!proposal.options.length&&<button className="fp-button primary" disabled={busy||!chosen}>Gewählten Vorschlag reservieren</button>}
  </div>
 </form>;
}

function OptionCard({option,venue,selected,onSelect}:{option:ProposalOption;venue:Venue;selected:boolean;onSelect:()=>void}){
 return <label className={`fp-option ${selected?"selected":""}`}>
  <input type="radio" name="option" value={option.key} checked={selected} onChange={onSelect}/>
  <span className="fp-option-head"><strong>{option.title}</strong><Tag tone={selected?"green":"neutral"}>{option.seats} Plätze</Tag></span>
  <span className="fp-option-summary">{option.summary}</span>
  <span className="fp-option-summary">{time(option.starts_at,venue.timezone)}–{time(option.ends_at,venue.timezone)}</span>
  <ul>{option.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
  {!!option.tradeoffs.length&&<ul className="fp-option-tradeoffs">{option.tradeoffs.map(item=><li key={item}><TriangleAlert size={14}/> {item}</li>)}</ul>}
 </label>;
}
