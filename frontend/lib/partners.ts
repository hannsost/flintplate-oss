import { request } from "./api";
export interface Partnership { id: string; partner_name: string; purpose: string; status: string; version: number; incoming: boolean; can_manage: boolean }
export interface DemandInput { title: string; location: string; starts_on: string; headcount: number; required_skills: string[] }
export interface SharedDemand extends DemandInput { id: string; version: number; status: string; offered_count: number; own: boolean }
export interface PartnerEvent { action: string; detail: string; actor_id: string | null; created_at: string }
export const partnerApi = {
  list: (t: string) => request<Partnership[]>("/partners", {}, t),
  invite: (t: string, target_slug: string, purpose: string) => request<Partnership>("/partners", { method: "POST", body: JSON.stringify({ target_slug, purpose }) }, t),
  decide: (t: string, p: Partnership, action: "accept" | "revoke") => request<Partnership>(`/partners/${p.id}/decision`, { method: "POST", body: JSON.stringify({ version: p.version, action }) }, t),
  demands: (t: string, id: string) => request<SharedDemand[]>(`/partners/${id}/demands`, {}, t),
  share: (t: string, id: string, d: DemandInput) => request<SharedDemand>(`/partners/${id}/demands`, { method: "POST", body: JSON.stringify(d) }, t),
  capacity: (t: string, id: string, d: SharedDemand, offered_count: number) => request<SharedDemand>(`/partners/${id}/demands/${d.id}/capacity`, { method: "PUT", body: JSON.stringify({ version: d.version, offered_count }) }, t),
  close: (t: string, id: string, d: SharedDemand) => request<SharedDemand>(`/partners/${id}/demands/${d.id}/close`, { method: "POST", body: JSON.stringify({ version: d.version }) }, t),
  events: (t: string, id: string) => request<PartnerEvent[]>(`/partners/${id}/events`, {}, t),
};
