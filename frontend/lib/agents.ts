import { request } from "./api";

export type AgentCapability = "job_check" | "onboarding_draft" | "ai_job_brief";
export interface AgentInput {
  name: string; owner_id: string; enabled: boolean; capability: AgentCapability;
  daily_task_limit: number; max_attempts: number; four_eyes: boolean;
}
export interface ManagedAgent extends Omit<AgentInput, "owner_id"> { id: string; version: number; owner_id: string | null }
export interface AgentOptions { can_manage: boolean; current_user_id: string; members: { id: string; name: string }[]; external_ai_enabled: boolean }
export interface AgentRun {
  id: string; agent_id: string; task_id: string; job_id: string; delegated_by: string | null; reviewer_id: string | null;
  status: string; version: number; source: Record<string, string>; output: string | null; output_origin: string | null;
  provider_model: string | null; review_note: string | null; reviewed_at: string | null; created_at: string;
  queue_status: string; attempts: number; max_attempts: number; last_error_code: string | null;
}
export interface AgentEvent { action: string; actor_id: string | null; created_at: string }
export const agentApi = {
  options: (token: string) => request<AgentOptions>("/agents/options", {}, token),
  list: (token: string) => request<ManagedAgent[]>("/agents", {}, token),
  create: (token: string, data: AgentInput) => request<ManagedAgent>("/agents", { method: "POST", body: JSON.stringify(data) }, token),
  update: (token: string, agent: ManagedAgent, data: AgentInput) => request<ManagedAgent>(`/agents/${agent.id}`, { method: "PUT", body: JSON.stringify({ ...data, expected_version: agent.version }) }, token),
  assign: (token: string, agent: ManagedAgent, data: { job_id: string; reviewer_id: string; title: string; instructions: string; authorize_ai: boolean; request_key: string }) => request<AgentRun>(`/agents/${agent.id}/tasks`, { method: "POST", body: JSON.stringify({ ...data, expected_version: agent.version }) }, token),
  runs: (token: string) => request<AgentRun[]>("/agents/runs", {}, token),
  events: (token: string, runId: string) => request<AgentEvent[]>(`/agents/runs/${runId}/events`, {}, token),
  review: (token: string, run: AgentRun, decision: "approve" | "reject", note: string) => request<AgentRun>(`/agents/runs/${run.id}/review`, { method: "POST", body: JSON.stringify({ expected_version: run.version, decision, note }) }, token),
  cancel: (token: string, run: AgentRun) => request<AgentRun>(`/agents/runs/${run.id}/cancel`, { method: "POST", body: JSON.stringify({ expected_version: run.version }) }, token),
};
