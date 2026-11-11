"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Check, ClipboardList, Clock3, History, Plus, RefreshCw } from "lucide-react";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, str, venueApi, type Member, type Venue } from "@/lib/flintplate";
import { labourLocalTime, labourTimeChoices, resolveLabourTime } from "@/lib/flintplate-labour";
import { useVenueMutation } from "@/lib/flintplate-pending";
import { openTasks, taskPage, taskUserId, taskActions, taskPriorities, taskStatuses, TASK_PATH, TASK_PENDING_PREFIX, type VenueTask, type TaskAction, type TaskCommand, type TaskPage } from "@/lib/flintplate-tasks";
import { Empty, Field, Loading, Modal, Tag, useLive, useNow } from "./shared";
import "./tasks.css";
const principal=()=>{const user=auth.getUser();return JSON.stringify([user?.tenant_id,user?.sub]);};
const actionNames:Record<TaskAction,string>={start:"Beginnen",done:"Erledigen",cancel:"Aufgabe abbrechen",reopen:"Wieder öffnen",reassign:"Neu zuweisen",edit:"Aufgabe bearbeiten"};
type Editor={kind:"create"}|{kind:TaskAction;task:VenueTask};
export function TasksPanel({venue,personal=false,onOpenHygiene}:{venue:Venue;personal?:boolean;onOpenHygiene?:()=>void}) {
  return <TasksView key={`${principal()}:${venue.id}:${personal}`} venue={venue} personal={personal} onOpenHygiene={onOpenHygiene}/>;
}
function TasksView({venue,personal,onOpenHygiene}:{venue:Venue;personal:boolean;onOpenHygiene?:()=>void}) {
  const manager=venue.role==="manager";
  const [userId,setUserId]=useState<string|null>(null),identity=useRef<string|null>(null);
  const [mine,setMine]=useState(personal||!manager),[includeClosed,setIncludeClosed]=useState(false);
  const [tasks,setTasks]=useState<VenueTask[]|null>(null),[members,setMembers]=useState<Member[]>([]),[next,setNext]=useState<string|null>(null);
  const [editor,setEditor]=useState<Editor|null>(null),[detail,setDetail]=useState<VenueTask|null>(null),[history,setHistory]=useState<TaskCommand[]>([]),[historyNext,setHistoryNext]=useState<string|null>(null);
  const [loading,setLoading]=useState(true),[reading,setReading]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState(""),[authorized,setAuthorized]=useState(true);
  const mounted=useRef(true),scope=useRef(principal()),detailId=useRef(""),readSequence=useRef(0),historyCursors=useRef(new Set<string>());
  const now=useNow(30000);
  const sameScope=useCallback(()=>mounted.current&&scope.current===principal(),[]);
  const load=useCallback(async()=>{
    const sequence=++readSequence.current;
    const [currentUserId,rows]=await Promise.all([
      identity.current?Promise.resolve(identity.current):taskUserId(auth.getUser()?.tenant_id??null,()=>sameScope()&&sequence===readSequence.current),
      includeClosed?taskPage(venue.id,mine,true):openTasks(venue.id,mine).then(items=>({items,next_before:null,has_more:false})),
    ]);
    if(sameScope()&&sequence===readSequence.current&&currentUserId){identity.current=currentUserId;setUserId(currentUserId);setTasks(rows.items);setNext(rows.has_more?rows.next_before:null);}
  },[venue.id,mine,includeClosed,sameScope]);
  const refreshDetail=useCallback(async()=>{
    const id=detailId.current;if(!id)return;
    const [row,page]=await Promise.all([venueApi<VenueTask>(venue.id,`/tasks/${id}`),venueApi<TaskPage<TaskCommand>>(venue.id,`/tasks/${id}/history?limit=50`)]);
    if(sameScope()&&detailId.current===id){setDetail(row);setHistory(page.items);setHistoryNext(page.has_more?page.next_before:null);historyCursors.current=new Set();}
  },[venue.id,sameScope]);
  const afterCommit=useCallback(async()=>{await load();await refreshDetail();},[load,refreshDetail]);
  const mutation=useVenueMutation(venue.id,TASK_PENDING_PREFIX,TASK_PATH,afterCommit);
  const locked=mutation.busy||!!mutation.pending||mutation.blocked||!mutation.ready||loading||reading||!authorized||!userId;
  useEffect(()=>{
    mounted.current=true;
    const changed=()=>{if(scope.current!==principal()){readSequence.current++;identity.current=null;setUserId(null);setTasks(null);setMembers([]);setEditor(null);setDetail(null);setHistory([]);setAuthorized(false);}};
    window.addEventListener(AUTH_CHANGED_EVENT,changed);window.addEventListener("storage",changed);
    return()=>{mounted.current=false;window.removeEventListener(AUTH_CHANGED_EVENT,changed);window.removeEventListener("storage",changed);};
  },[]);
  useEffect(()=>{let active=true;setLoading(true);void load().catch(cause=>{if(active&&sameScope())setError(message(cause));}).finally(()=>{if(active&&sameScope())setLoading(false);});return()=>{active=false;};},[load,sameScope]);
  useEffect(()=>{if(!manager)return;void venueApi<Member[]>(venue.id,"/members").then(rows=>{if(sameScope())setMembers(rows.filter(row=>row.active));}).catch(cause=>{if(sameScope())setError(message(cause));});},[venue.id,manager,sameScope]);
  useLive(async()=>{if(!mutation.pending&&!mutation.busy&&!reading&&!includeClosed)await load();},15000);
  const when=(value:string)=>new Date(value).toLocaleString("de-DE",{timeZone:venue.timezone,dateStyle:"medium",timeStyle:"short"});
  async function complete(ok:boolean,label:string){if(ok&&sameScope()){setEditor(null);setNotice(label);}}
  async function reload(){if(reading)return;setReading(true);setError("");try{await load();await refreshDetail();}catch(cause){if(sameScope())setError(message(cause));}finally{if(sameScope())setReading(false);}}
  async function older(){if(!next||reading)return;setReading(true);const before=next;try{const page=await taskPage(venue.id,mine,true,before);if(sameScope()){setTasks(rows=>[...new Map([...(rows??[]),...page.items].map(row=>[row.id,row])).values()]);setNext(page.has_more?page.next_before:null);}}catch(cause){if(sameScope())setError(message(cause));}finally{if(sameScope())setReading(false);}}
  async function showDetails(task:VenueTask){if(reading||mutation.busy)return;setEditor(null);detailId.current=task.id;setDetail(task);setHistory([]);setHistoryNext(null);setReading(true);setError("");try{await refreshDetail();}catch(cause){if(sameScope())setError(message(cause));}finally{if(sameScope())setReading(false);}}
  async function olderHistory(){if(!detail||!historyNext||reading)return;setReading(true);const id=detail.id,before=historyNext;try{
    const page=await venueApi<TaskPage<TaskCommand>>(venue.id,`/tasks/${id}/history?limit=50&before=${encodeURIComponent(before)}`);
    if(page.items.some(row=>row.task_id!==id)||page.has_more&&(!page.next_before||page.next_before===before||historyCursors.current.has(page.next_before)))throw new Error("Die Aufgabenhistorie konnte nicht vollständig gelesen werden.");
    if(sameScope()&&detailId.current===id){historyCursors.current.add(before);setHistory(rows=>[...new Map([...rows,...page.items].map(row=>[row.id,row])).values()]);setHistoryNext(page.has_more?page.next_before:null);}
  }catch(cause){if(sameScope())setError(message(cause));}finally{if(sameScope())setReading(false);}}
  function begin(task:VenueTask,kind:TaskAction){if(locked)return;setDetail(null);detailId.current="";setEditor({kind,task});setError("");setNotice("");mutation.clearError();}
  async function start(task:VenueTask){if(locked)return;await complete(await mutation.send(`/tasks/${task.id}/action`,{version:task.version,action:"start",note:"Aufgabe übernommen"},`Beginn · ${task.title}`),"Aufgabe begonnen und mit „Aufgabe übernommen“ protokolliert.");}
  async function done(task:VenueTask){if(locked)return;if(task.require_completion_note){begin(task,"done");return;}await complete(await mutation.send(`/tasks/${task.id}/action`,{version:task.version,action:"done",note:"Aufgabe erledigt"},`Erledigung · ${task.title}`),"Erledigt. Dein Name und der Zeitpunkt sind im Verlauf dokumentiert.");}
  const feedback=<>{(error||mutation.error)&&<p className="fp-notice error" role="alert">{error||mutation.error}</p>}{notice&&<p className="fp-notice" role="status">{notice}</p>}{mutation.pending&&<div className="fp-notice"><strong>{mutation.pending.label}</strong><p>Die Rückmeldung steht aus. Der vollständige Auftrag bleibt bis zur Bestätigung gespeichert.</p><button className="fp-button" disabled={mutation.busy||mutation.blocked||!userId||loading} onClick={()=>void mutation.retry().then(ok=>complete(ok,"Aufgabenvorgang bestätigt und aktueller Stand geladen."))}><RefreshCw size={16}/> Aufgabenvorgang erneut prüfen</button></div>}</>;
  if(!authorized)return <p role="alert" className="fp-notice error">Bitte erneut persönlich anmelden.</p>;
  return <section className="fp-tasks" aria-label={`Aufgaben ${venue.name}`}>
    <div className="fp-section-head"><div><span className="fp-eyebrow">{venue.name}</span><h2>{personal?"Meine Aufgaben":"Aufgaben im Betrieb"}</h2><p>Klare Zuständigkeit. Nachvollziehbarer Abschluss.</p></div>{manager&&!personal&&<button className="fp-button primary" disabled={locked||!members.length} onClick={()=>{setEditor({kind:"create"});setNotice("");setError("");}}><Plus size={18}/> Aufgabe zuweisen</button>}</div>
    {feedback}<div className="fp-task-filters">{manager&&!personal&&<label><input type="checkbox" checked={mine} disabled={locked} onChange={event=>setMine(event.target.checked)}/> Nur meine Aufgaben</label>}<label><input type="checkbox" checked={includeClosed} disabled={locked} onChange={event=>setIncludeClosed(event.target.checked)}/> Auch erledigte und abgebrochene</label><button className="fp-button" disabled={reading||mutation.busy} onClick={()=>void reload()}><RefreshCw size={16}/> Aktualisieren</button></div>
    <p className="fp-description">{includeClosed?`${tasks?.length??0} geladene Aufgaben · neueste Zuweisungen zuerst`:`${tasks?.length??0} offene Aufgaben · Priorität, dann Fälligkeit`} · Termine in {venue.timezone}</p>
    {loading?<Loading/>:tasks?.length?<div className="fp-task-list">{tasks.map(task=>{const actions=taskActions(task,userId??"",manager&&!personal),overdue=task.due_at&&Date.parse(task.due_at)<now&&["open","in_progress"].includes(task.status);return <article className="fp-panel fp-task-card" key={task.id} data-task-id={task.id}>
      <div className="fp-task-heading"><h3>{task.title}</h3><div className="fp-inline wrap"><Tag tone={task.status==="done"?"green":"neutral"}>{taskStatuses[task.status]}</Tag><Tag tone={["urgent","high"].includes(task.priority)?"amber":"neutral"}>{taskPriorities[task.priority]}</Tag></div></div>
      <p className="fp-task-assignee">Zuständig: <strong>{task.assigned_to_name}</strong></p><p className={overdue?"fp-task-overdue":"fp-description"}><Clock3 size={15}/>{overdue?"Überfällig · ":""}{task.due_at?when(task.due_at):"Ohne Fälligkeit"}</p>{task.description&&<p className="fp-task-note">{task.description}</p>}
      {task.status==="done"&&<p className="fp-task-evidence"><Check size={16}/> {task.worker_note||"Abschluss im Verlauf ansehen"}{task.completed_at&&<small>{when(task.completed_at)}</small>}</p>}
      <div className="fp-task-actions">{actions.includes("start")&&<button className="fp-button" disabled={locked} onClick={()=>void start(task)}>Beginnen</button>}{actions.includes("done")&&<button className="fp-button primary" disabled={locked} onClick={()=>void done(task)}><Check size={17}/> Erledigen</button>}<button className="fp-button" disabled={reading||mutation.busy} onClick={()=>void showDetails(task)}><History size={17}/> Details & Verlauf</button></div>{actions.includes("done")&&<small>{task.require_completion_note?"Zum Abschluss ist eine kurze Notiz erforderlich.":"Erledigung wird mit deinem Namen und Zeitpunkt protokolliert."}</small>}
    </article>;})}</div>:<Empty title="Hier ist gerade nichts offen">{includeClosed?"Für diese Auswahl sind keine Aufgaben vorhanden.":"Neue Zuweisungen erscheinen hier. Erledigte Aufgaben bleiben im Verlauf erhalten."}</Empty>}
    {next&&<button className="fp-button" disabled={reading||mutation.busy} onClick={()=>void older()}>Ältere Aufgaben laden</button>}
    <aside className="fp-panel fp-task-hygiene"><ClipboardList size={22}/><div><h3>Hygienekontrollen bleiben eigene Nachweise</h3><p>Messwerte und Nachkontrollen erfasst du unter Produktion & Hygiene → Kontrollpläne. Ein Aufgabenabschluss ersetzt keine Kontrolle.</p></div>{onOpenHygiene?<button className="fp-button" onClick={onOpenHygiene}>Kontrollpläne öffnen <ArrowRight size={16}/></button>:<a className="fp-button" href="/gastro">Betrieb öffnen <ArrowRight size={16}/></a>}</aside>
    {editor&&<Modal title={editor.kind==="create"?"Aufgabe zuweisen":actionNames[editor.kind]} closeDisabled={mutation.busy} onClose={()=>setEditor(null)}>{feedback}<TaskForm key={editor.kind==="create"?"create":`${editor.task.id}:${editor.task.version}:${editor.kind}`} editor={editor} venue={venue} members={members} locked={locked} onSave={async payload=>{const path=editor.kind==="create"?"/tasks":`/tasks/${editor.task.id}/action`;await complete(await mutation.send(path,payload,editor.kind==="create"?`Zuweisung · ${String(payload.title)}`:`${actionNames[editor.kind]} · ${editor.task.title}`),"Aufgabe gespeichert. Die Änderung ist im Verlauf belegt.");}}/></Modal>}
    {detail&&!editor&&<Modal title="Aufgabe & Verlauf" closeDisabled={mutation.busy} onClose={()=>{setDetail(null);detailId.current="";}}>{feedback}<h3>{detail.title}</h3><p><strong>{detail.assigned_to_name}</strong> · {taskStatuses[detail.status]} · Stand {detail.version}</p><p>{detail.due_at?`Fällig ${when(detail.due_at)} (${venue.timezone})`:"Ohne Fälligkeit"} · {taskPriorities[detail.priority]}</p><p className="fp-task-note">{detail.description}</p><div className="fp-inline wrap">{taskActions(detail,userId??"",manager&&!personal).filter(action=>action!=="start").map(action=><button className="fp-button" key={action} disabled={locked} onClick={()=>begin(detail,action)}>{actionNames[action]}</button>)}</div>{reading&&!history.length?<Loading/>:<div className="fp-task-history">{history.map(command=><article className="fp-panel" key={command.id}><strong>{command.kind==="create"?"Zugewiesen":actionNames[command.kind as TaskAction]??"Änderung"} · {command.actor_name} · {when(command.created_at)}</strong><p className="fp-task-note">{command.note}</p><small>{command.before?`${taskStatuses[command.before.status]} → ${taskStatuses[command.after.status]}`:"Zugewiesen"} · Stand {command.after.version}</small><details><summary>Gespeicherten Aufgabenstand ansehen</summary><p>{command.after.title}</p><p>Zuständig: {command.after.assigned_to_name}</p><p>{command.after.due_at?when(command.after.due_at):"Ohne Fälligkeit"} · {taskPriorities[command.after.priority]}</p><p className="fp-task-note">{command.after.description}</p>{command.after.worker_note&&<p>Abschlussnotiz: {command.after.worker_note}</p>}</details></article>)}</div>}{historyNext&&<button className="fp-button" disabled={reading||mutation.busy} onClick={()=>void olderHistory()}>Ältere Änderungen laden</button>}</Modal>}
  </section>;
}
function TaskForm({editor,venue,members,locked,onSave}:{editor:Editor;venue:Venue;members:Member[];locked:boolean;onSave:(payload:Record<string,unknown>)=>Promise<void>}) {
  const task=editor.kind==="create"?null:editor.task, fields=editor.kind==="create"||editor.kind==="edit";
  const [due,setDue]=useState(task?.due_at?labourLocalTime(task.due_at,venue.timezone):""),[choice,setChoice]=useState(task?.due_at?new Date(Math.floor(Date.parse(task.due_at)/60000)*60000).toISOString():""),[error,setError]=useState("");
  const choices=due?labourTimeChoices(due,venue.timezone):[];
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();if(locked)return;setError("");const form=new FormData(event.currentTarget);try{
    const payload:Record<string,unknown>=editor.kind==="create"?{assigned_to:str(form,"person")}:{version:editor.task.version,action:editor.kind,note:str(form,"note")||(editor.kind==="done"?"Aufgabe erledigt":"")};
    if(editor.kind==="reassign")payload.assigned_to=str(form,"person");
    if(fields)Object.assign(payload,{title:str(form,"title"),description:str(form,"description"),priority:str(form,"priority"),require_completion_note:form.has("require_note"),due_at:due?resolveLabourTime(due,venue.timezone,choice,task?.due_at??undefined):null});
    await onSave(payload);
  }catch(cause){setError(message(cause));}}
  return <form className="fp-tasks fp-task-form" onSubmit={submit}>{error&&<p role="alert" className="fp-notice error">{error}</p>}<fieldset disabled={locked} className="fp-fieldset">
    {task&&<p><strong>{task.title}</strong> · {task.assigned_to_name} · Stand {task.version}</p>}
    {(editor.kind==="create"||editor.kind==="reassign")&&<Field label="Zuständige Person"><select name="person" defaultValue={editor.kind==="reassign"?"":members.length===1?members[0].user_id:""} required><option value="">Person wählen</option>{members.filter(person=>editor.kind!=="reassign"||person.user_id!==task?.assigned_to).map(person=><option key={person.user_id} value={person.user_id}>{person.full_name}</option>)}</select></Field>}
    {fields&&<><Field label="Aufgabe"><input name="title" maxLength={300} required defaultValue={task?.title??""} autoFocus/></Field><Field label="Notiz / Arbeitsanweisung"><textarea name="description" rows={3} maxLength={4000} defaultValue={task?.description??""}/></Field><div className="fp-two"><Field label="Priorität"><select name="priority" defaultValue={task?.priority??"medium"}>{Object.entries(taskPriorities).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></Field><Field label={`Fällig (${venue.timezone}, optional)`}><input type="datetime-local" value={due} onChange={event=>{setDue(event.target.value);setChoice("");}}/></Field></div>{due&&choices.length===0&&<p className="fp-notice error">Diese Ortszeit existiert nicht. Bitte den Termin korrigieren.</p>}<label className="fp-task-note-choice"><input type="checkbox" name="require_note" defaultChecked={task?.require_completion_note??false}/> Abschlussnotiz erforderlich</label><small>Nur einschalten, wenn zum Abschluss eine zusätzliche Beschreibung oder ein Belegbezug benötigt wird.</small>{choices.length>1&&<Field label="Zeitversatz bei der Zeitumstellung"><select value={choice} onChange={event=>setChoice(event.target.value)} required><option value="" disabled>Diese Uhrzeit kommt zweimal vor – Versatz wählen</option>{choices.map(value=><option key={value.iso} value={value.iso}>{value.label}</option>)}</select></Field>}</>}
    {editor.kind!=="create"&&<Field label={editor.kind==="done"?`Abschlussnotiz${task?.require_completion_note?" / Nachweis":" (optional)"}`:"Grund / Notiz zur Änderung"}><textarea name="note" minLength={3} maxLength={1000} rows={3} required={editor.kind!=="done"||!!task?.require_completion_note} placeholder={editor.kind==="done"?"Was wurde erledigt? Ergebnis oder Belegbezug kurz festhalten.":"Änderung kurz erläutern."}/></Field>}
    {editor.kind==="done"&&<p className="fp-description">Deine persönliche Bestätigung wird mit Name, Zeitpunkt und Aufgabenstand gespeichert. {task?.require_completion_note?"Für diese Aufgabe ist eine eigene Abschlussnotiz erforderlich.":"Ohne eigene Notiz lautet der Eintrag „Aufgabe erledigt“."} Messpflichtige Hygienekontrollen weiterhin im Kontrollplan dokumentieren.</p>}
    {editor.kind==="cancel"&&<p className="fp-description">Die Aufgabe wird abgebrochen. Zuweisung und bisheriger Verlauf bleiben erhalten.</p>}
    <button className="fp-button primary wide" disabled={locked||!!due&&!choices.length}>{editor.kind==="create"?"Aufgabe verbindlich zuweisen":editor.kind==="done"?task?.require_completion_note?"Erledigung mit Nachweis bestätigen":"Erledigung bestätigen":`${actionNames[editor.kind]} und protokollieren`}</button>
  </fieldset></form>;
}
