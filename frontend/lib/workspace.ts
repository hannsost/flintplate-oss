import { request, type TokenResponse, type UserRead } from "./api";

export interface WorkspaceAction {
  id: string; kind: string; title: string; detail: string;
  href: string; action_label: string; due_at: string | null; urgent: boolean;
}
export interface Person {
  id: string; full_name: string | null; email: string; role: string;
  headline: string | null; location: string | null;
}
export interface PersonDetail extends Person {
  summary: string | null;
  skills: { name: string; source: string | null }[];
  experience: { title: string; company: string; description: string | null; source: string | null }[];
  applications: { id: string; position: string; status: string; updated_at: string }[];
  actions: WorkspaceAction[];
}
export interface Invitation {
  id: string; email: string; role: string; expires_at: string;
  accepted_at: string | null; revoked_at: string | null;
}
const base = "/companies/workspace";
export const workspaceApi = {
  today: (token: string) => request<{ generated_at: string; actions: WorkspaceAction[] }>(`${base}/today`, {}, token),
  people: (token: string, params: URLSearchParams, signal?: AbortSignal) => request<{ total: number; people: Person[] }>(`${base}/people?${params}`, { signal }, token),
  person: (token: string, id: string, signal?: AbortSignal) => request<PersonDetail>(`${base}/people/${id}`, { signal }, token),
  members: (token: string) => request<{ owner_id: string | null; members: UserRead[]; invitations: Invitation[] }>(`${base}/members`, {}, token),
  invite: (token: string, email: string, role: string) => request<Invitation & { token: string }>(`${base}/invitations`, { method: "POST", body: JSON.stringify({ email, role }) }, token),
  revoke: (token: string, id: string) => request<void>(`${base}/invitations/${id}`, { method: "DELETE" }, token),
  accept: (token: string, invitation: string) => request<TokenResponse>(`${base}/invitations/accept`, { method: "POST", body: JSON.stringify({ token: invitation }) }, token),
  role: (token: string, id: string, role: string) => request<UserRead>(`${base}/members/${id}`, { method: "PATCH", body: JSON.stringify({ role }) }, token),
};
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Die Aktion konnte nicht abgeschlossen werden.";
}
export const applicationLabels: Record<string, string> = {
  research: "Recherche", applied: "Beworben", screening: "Sichtung", interview: "Interview",
  offer: "Angebot", rejected: "Abgelehnt", withdrawn: "Zurückgezogen",
};
