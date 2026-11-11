"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { MessagesSquare, Plus, Send, Trash2 } from "lucide-react";
import { date, message, time, venueApi, type ChatChannel, type ChatMessage, type Venue } from "@/lib/flintplate";
import { Empty, Field, Modal, Tag, useLive } from "./shared";

/** Written once, never rewritten: messages can be removed but not edited. */
export function TeamChat({venue,compact=false}:{venue:Venue;compact?:boolean}){
 const [channels,setChannels]=useState<ChatChannel[]>([]);
 const [current,setCurrent]=useState("");
 const [messages,setMessages]=useState<ChatMessage[]>([]);
 const [add,setAdd]=useState(false);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const bottom=useRef<HTMLDivElement>(null);

 const load=useCallback(async()=>{
  const rows=await venueApi<ChatChannel[]>(venue.id,"/chat/channels");
  setChannels(rows);
  const channel=current||rows[0]?.id||"";
  if(!current&&channel)setCurrent(channel);
  if(channel){
   setMessages(await venueApi<ChatMessage[]>(venue.id,`/chat/channels/${channel}/messages`));
   await venueApi(venue.id,`/chat/channels/${channel}/read`,"POST").catch(()=>undefined);
  }
 },[venue.id,current]);

 useEffect(()=>{load().catch(e=>setError(message(e)));},[load]);
 useLive(load,12000);
 useEffect(()=>{bottom.current?.scrollIntoView({block:"nearest"});},[messages.length]);

 async function send(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  const form=event.currentTarget;
  const text=String(new FormData(form).get("text")??"").trim();
  if(!text||!current)return;
  setBusy(true);setError("");
  try{await venueApi(venue.id,`/chat/channels/${current}/messages`,"POST",{text});form.reset();await load();}
  catch(e){setError(message(e));}
  finally{setBusy(false);}
 }

 const open=channels.find(row=>row.id===current);
 return <section className="fp-panel">
  <div className="fp-section-head">
   <div><h2>Team-Chat</h2><p>{open?.topic||"Kurze Absprachen für die Schicht. Nachrichten laufen nach der eingestellten Frist ab."}</p></div>
   {venue.role==="manager"&&<button className="fp-button" onClick={()=>setAdd(true)}><Plus size={16}/> Kanal</button>}
  </div>
  {error&&<p className="fp-notice error" role="alert">{error}</p>}

  {channels.length>1&&<div className="fp-tabs small">{channels.map(row=><button key={row.id} className={row.id===current?"active":""} onClick={()=>{setCurrent(row.id);setMessages([]);}}>
   {row.name}{row.unread>0&&row.id!==current?<span className="fp-badge">{row.unread}</span>:null}
  </button>)}</div>}

  <div className={`fp-chat ${compact?"compact":""}`}>
   {messages.map(row=><article className={`fp-message ${row.mine?"mine":""}`} key={row.id}>
    <header><strong>{row.mine?"Du":row.author_name}</strong><small>{time(row.created_at,venue.timezone)} · {date(row.created_at,venue.timezone)}</small></header>
    <p>{row.text}</p>
    {(row.mine||venue.role==="manager")&&<button className="fp-text-button" disabled={busy} aria-label="Nachricht löschen" onClick={async()=>{
     setBusy(true);setError("");
     try{await venueApi(venue.id,`/chat/channels/${current}/messages/${row.id}`,"DELETE");await load();}
     catch(e){setError(message(e));}
     finally{setBusy(false);}
    }}><Trash2 size={13}/></button>}
   </article>)}
   {!messages.length&&<Empty title="Noch nichts geschrieben"><MessagesSquare size={16}/> Die erste Nachricht sieht das ganze Team dieser Betriebsstätte.</Empty>}
   <div ref={bottom}/>
  </div>

  <form className="fp-chat-form" onSubmit={send}>
   <input name="text" required maxLength={2000} placeholder="Nachricht an das Team …" aria-label="Nachricht"/>
   <button className="fp-button primary" disabled={busy||!current}><Send size={16}/> Senden</button>
  </form>
  <p className="fp-hint">Nachrichten lassen sich löschen, aber nicht bearbeiten. Die Betriebsleitung kann jede Nachricht entfernen.</p>

  {add&&<Modal title="Kanal anlegen" onClose={()=>setAdd(false)}>
   <form onSubmit={async e=>{e.preventDefault();const f=new FormData(e.currentTarget);
    setBusy(true);setError("");
    try{await venueApi(venue.id,"/chat/channels","POST",{name:String(f.get("name")),topic:String(f.get("topic"))});await load();setAdd(false);}
    catch(err){setError(message(err));}
    finally{setBusy(false);}}}>
    <Field label="Name"><input name="name" required minLength={2} maxLength={60} placeholder="Küche"/></Field>
    <Field label="Worum geht es hier?"><input name="topic" maxLength={200} placeholder="Absprachen am Pass."/></Field>
    <button className="fp-button primary wide" disabled={busy}>Anlegen</button>
   </form>
  </Modal>}
 </section>;
}

export function ChatBadge({channels}:{channels:ChatChannel[]}){
 const unread=channels.reduce((sum,row)=>sum+row.unread,0);
 return unread?<Tag tone="green">{unread} neu</Tag>:null;
}
