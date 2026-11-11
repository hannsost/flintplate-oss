import { request } from "./api";
export interface Offer { id: string; application_id: string; title: string; terms: string; start_date: string; expires_on: string; status: string; version: number; shared_at: string | null; created_at: string }
export interface PrivateOffer extends Offer { person_id: string; person_name: string; created_by: string | null; approver_id: string | null; events: { actor_id: string | null; status: string; version: number; note: string | null; title: string; terms: string; start_date: string; expires_on: string; created_at: string }[] }
export interface OfferContent { title: string; terms: string; start_date: string; expires_on: string }
export interface JourneyStep { id: string; title: string; audience: string; assignee_id: string | null; due_on: string; completed_at: string | null; completed_by: string | null }
export interface Journey { id: string; offer_id: string; person_id: string; person_name: string; title: string; owner_id: string | null; start_date: string; template: string; activated_at: string | null; completed: number; total: number; steps: JourneyStep[] }
export interface JourneyTemplate { key: string; title: string; steps: { title: string; audience: string; days_from_start: number }[] }
export interface TeamOption { id: string; full_name: string; role: string }
const base = "/companies/workspace";
export const offerStatus: Record<string, string> = { draft: "Entwurf", review: "In Freigabe", approved: "Freigegeben", shared: "Antwort ausstehend", accepted: "Angenommen", declined: "Abgelehnt", withdrawn: "Zurückgezogen" };
export const journeysApi = {
  approvalPolicy: (token: string) => request<{ self_approval_allowed: boolean }>(`${base}/journeys/approval-policy`, {}, token),
  team: (token: string) => request<TeamOption[]>(`${base}/journeys/team`, {}, token),
  offers: (token: string, applicationId?: string, offset = 0) => request<PrivateOffer[]>(`${base}/offers?offset=${offset}${applicationId ? `&application_id=${applicationId}` : ""}`, {}, token),
  mine: (token: string) => request<Offer[]>(`${base}/offers/mine`, {}, token),
  save: (token: string, content: OfferContent, applicationId: string, offer?: PrivateOffer) => request<PrivateOffer>(`${base}/offers${offer ? `/${offer.id}` : ""}`, { method: offer ? "PATCH" : "POST", body: JSON.stringify({ ...content, ...(offer ? { version: offer.version } : { application_id: applicationId }) }) }, token),
  act: (token: string, offer: PrivateOffer, action: string, approverId?: string, note?: string) => request<PrivateOffer>(`${base}/offers/${offer.id}/actions`, { method: "POST", body: JSON.stringify({ version: offer.version, action, approver_id: approverId || null, note: note || null }) }, token),
  decide: (token: string, offer: Offer, decision: "accepted" | "declined") => request<Offer>(`${base}/offers/${offer.id}/decision`, { method: "POST", body: JSON.stringify({ version: offer.version, decision }) }, token),
  templates: (token: string) => request<JourneyTemplate[]>(`${base}/onboarding/templates`, {}, token),
  cases: (token: string, mine = false) => request<Journey[]>(`${base}/onboarding${mine ? "/mine" : ""}`, {}, token),
  start: (token: string, offerId: string, template: string, ownerId: string) => request<Journey>(`${base}/onboarding`, { method: "POST", body: JSON.stringify({ offer_id: offerId, template, owner_id: ownerId }) }, token),
  step: (token: string, caseId: string, data: { title: string; audience: string; due_on: string; assignee_id: string | null }, id?: string) => request<JourneyStep>(`${base}/onboarding/${caseId}/steps${id ? `/${id}` : ""}`, { method: id ? "PATCH" : "POST", body: JSON.stringify(data) }, token),
  complete: (token: string, caseId: string, step: JourneyStep) => request<JourneyStep>(`${base}/onboarding/${caseId}/steps/${step.id}/completion`, { method: "POST", body: JSON.stringify({ completed: !step.completed_at }) }, token),
  activate: (token: string, caseId: string, employmentType: string) => request<Journey>(`${base}/onboarding/${caseId}/activate`, { method: "POST", body: JSON.stringify({ confirmed: true, employment_type: employmentType }) }, token),
};
