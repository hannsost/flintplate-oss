import { api, venueApi } from "./flintplate";
export const TASK_PENDING_PREFIX = "flintplate:task-pending:v1:";
export const TASK_PATH = /^\/tasks(?:\/[a-f0-9-]+\/action)?$/i;
export const taskPriorities = { low: "Niedrig", medium: "Normal", high: "Hoch", urgent: "Dringend" };
export const taskStatuses = { open: "Offen", in_progress: "In Arbeit", done: "Erledigt", cancelled: "Abgebrochen" };
export type TaskPriority = keyof typeof taskPriorities;
export type TaskStatus = keyof typeof taskStatuses;
export type TaskAction = "start" | "done" | "cancel" | "reopen" | "reassign" | "edit";
export interface VenueTask { id:string; venue_id:string; title:string; description:string|null; require_completion_note:boolean; assigned_to:string; assigned_to_name:string; assigned_by:string|null; assigned_by_name:string|null; due_at:string|null; priority:TaskPriority; status:TaskStatus; version:number; worker_note:string|null; completed_at:string|null; created_at:string; updated_at:string }
export interface TaskPage<T=VenueTask> { items:T[]; next_before:string|null; has_more:boolean }
export interface TaskCommand { id:string; task_id:string; actor_id:string; actor_name:string; kind:string; note:string; before:VenueTask|null; after:VenueTask; created_at:string }
/** JWT sub is an email address in PalmScout, not the assignment's user UUID.
 * Keep claims for session scoping and obtain identity from the authenticated API. */
export async function taskUserId(tenantId:string|null, stillCurrent:()=>boolean):Promise<string|null> {
  const user=await api<{id:string;tenant_id:string|null}>("/users/me");
  if(!stillCurrent())return null;
  if(user.tenant_id!==tenantId||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(user.id))throw new Error("Die persönliche Aufgabenberechtigung konnte nicht bestätigt werden. Bitte erneut laden.");
  return user.id;
}
export function taskActions(task:VenueTask, userId:string, manager:boolean):TaskAction[] {
  const values:TaskAction[]=[];
  if (task.assigned_to===userId && task.status==="open") values.push("start");
  if (task.assigned_to===userId && ["open","in_progress"].includes(task.status)) values.push("done");
  if (manager) values.push(...(["done","cancelled"].includes(task.status) ? ["reopen" as const] : ["edit" as const,"reassign" as const,"cancel" as const]));
  return values;
}
export async function taskPage(venueId:string, mine:boolean, includeClosed:boolean, before="") {
  const page=await venueApi<TaskPage>(venueId,`/tasks?mine=${mine}&include_closed=${includeClosed}&limit=50${before?`&before=${encodeURIComponent(before)}`:""}`);
  if (page.items.some(row=>row.venue_id!==venueId) || (page.has_more && (!page.items.length || !page.next_before || page.next_before===before))) throw new Error("Die Aufgabenliste konnte nicht vollständig gelesen werden. Bitte erneut laden.");
  return page;
}
/** Read every open task so an old, urgent assignment cannot disappear behind
 * newer completed tasks. Closed history remains explicitly paginated. */
export async function openTasks(venueId:string,mine:boolean) {
  const rows=new Map<string,VenueTask>(), seen=new Set<string>();let before="";
  for (;;) {
    const page=await taskPage(venueId,mine,false,before);
    for (const row of page.items) rows.set(row.id,row);
    if (!page.has_more) return [...rows.values()].sort(compareTasks);
    if (rows.size>=10000 || seen.has(page.next_before!)) throw new Error("Die offene Aufgabenliste ist zu groß oder unvollständig. Bitte die Betriebsleitung um Prüfung bitten.");
    before=page.next_before!;seen.add(before);
  }
}
export function compareTasks(a:VenueTask,b:VenueTask) {
  const rank={urgent:0,high:1,medium:2,low:3};
  return rank[a.priority]-rank[b.priority] || (a.due_at?Date.parse(a.due_at):Infinity)-(b.due_at?Date.parse(b.due_at):Infinity) || a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id);
}
