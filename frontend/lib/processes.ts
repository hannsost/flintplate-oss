import { request } from "./api";
export type ProcessAction = "job_check" | "message_draft" | "ai_job_brief" | "internal_notification";
export interface ProcessStep { action: ProcessAction; title: string; text: string; mode: "automatic" | "review" }
export interface ProcessInput { name: string; enabled: boolean; four_eyes: boolean; steps: ProcessStep[] }
export interface ProcessTemplate extends ProcessInput { id: string; version: number; updated_at: string }
export interface ProcessRun {
  id: string; template_id: string; template_version: number; job_id: string; created_by: string | null; name: string;
  status: string; version: number; cursor: number; four_eyes: boolean; source: Record<string, string>; steps: ProcessStep[];
  results: { step: number; action: string; title: string; output: string; origin: string; status: string }[];
  created_at: string; events: { id: string; actor_id: string | null; action: string; step: number; note: string; created_at: string }[];
}
export const processApi = {
  templates: (t: string) => request<ProcessTemplate[]>("/processes/templates", {}, t),
  create: (t: string, d: ProcessInput) => request<ProcessTemplate>("/processes/templates", { method: "POST", body: JSON.stringify(d) }, t),
  update: (t: string, id: string, d: ProcessInput & { version: number }) => request<ProcessTemplate>(`/processes/templates/${id}`, { method: "PUT", body: JSON.stringify(d) }, t),
  start: (t: string, p: ProcessTemplate, jobId: string, key: string, authorizeAI: boolean) => request<ProcessRun>(`/processes/templates/${p.id}/runs`, { method: "POST", body: JSON.stringify({ job_id: jobId, request_key: key, template_version: p.version, authorize_ai: authorizeAI }) }, t),
  runs: (t: string) => request<ProcessRun[]>("/processes/runs", {}, t),
  detail: (t: string, id: string) => request<ProcessRun>(`/processes/runs/${id}`, {}, t),
  review: (t: string, run: ProcessRun, decision: "approve" | "reject" | "cancel", note: string) => request<ProcessRun>(`/processes/runs/${run.id}/review`, { method: "POST", body: JSON.stringify({ version: run.version, decision, note }) }, t),
};
export const processActions: Record<ProcessAction, string> = { job_check: "Stellenangaben prüfen", message_draft: "Nachricht vorbereiten", ai_job_brief: "KI-Stellenbriefing", internal_notification: "Interne Benachrichtigung" };
export const processStatuses: Record<string, string> = { running: "In Arbeit", awaiting_review: "Prüfung erforderlich", blocked: "Blockiert", completed: "Abgeschlossen", rejected: "Abgelehnt", cancelled: "Abgebrochen", approved: "Freigegeben" };
