import { request } from "./api";
export type Provider = "google" | "microsoft";
export interface Connection { provider: Provider; configured: boolean; connected: boolean; email: string | null; detail: string | null }
export interface MessageDraft { id: string; person_id: string; author_id: string | null; recipient: string; subject: string; body: string; status: string; provider: string | null; sent_at: string | null; created_at: string }
export interface Booking { id: string; position: string; slots: string[]; duration_minutes: number; expires_at: string; booked_at: string | null; schedule_id: string | null }
const base = "/companies/workspace";
export interface InboxMessage { id: string; subject: string; sender: string; preview: string; received_at: string }
export interface InboxRead { provider: Provider; messages: InboxMessage[]; limited: boolean; days: number }
export const communicationApi = {
  inbox: (token: string, personId: string, provider: Provider) => request<InboxRead>(`${base}/messages/inbox?person_id=${encodeURIComponent(personId)}&provider=${provider}`, {}, token),
  connections: (token: string) => request<Connection[]>(`${base}/connections`, {}, token),
  authorize: (token: string, provider: Provider) => request<{ url: string }>(`${base}/connections/${provider}/authorize`, { method: "POST" }, token),
  callback: (token: string, state: string, code: string) => request<Connection>(`${base}/connections/callback`, { method: "POST", body: JSON.stringify({ state, code }) }, token),
  disconnect: (token: string, provider: Provider) => request<void>(`${base}/connections/${provider}`, { method: "DELETE" }, token),
  messages: (token: string, personId: string) => request<MessageDraft[]>(`${base}/messages?person_id=${encodeURIComponent(personId)}`, {}, token),
  save: (token: string, data: { person_id: string; subject: string; body: string }, id?: string) => request<MessageDraft>(`${base}/messages${id ? `/${id}` : ""}`, { method: id ? "PATCH" : "POST", body: JSON.stringify(data) }, token),
  discard: (token: string, id: string) => request<void>(`${base}/messages/${id}`, { method: "DELETE" }, token),
  send: (token: string, id: string, provider: Provider) => request<MessageDraft>(`${base}/messages/${id}/send`, { method: "POST", body: JSON.stringify({ provider, confirmed: true }) }, token),
  bookings: (token: string, applicationId: string) => request<Booking[]>(`${base}/bookings?application_id=${applicationId}`, {}, token),
  booking: (token: string, applicationId: string, slots: string[], minutes: number) => request<Booking & { token: string }>(`${base}/bookings`, { method: "POST", body: JSON.stringify({ application_id: applicationId, slots, duration_minutes: minutes }) }, token),
  preview: (token: string, secret: string) => request<Booking>(`${base}/bookings/preview`, { method: "POST", body: JSON.stringify({ token: secret }) }, token),
  reserve: (token: string, secret: string, scheduledAt: string) => request<{ schedule_id: string; scheduled_at: string; duration_minutes: number }>(`${base}/bookings/reserve`, { method: "POST", body: JSON.stringify({ token: secret, scheduled_at: scheduledAt }) }, token),
  revoke: (token: string, id: string) => request<void>(`${base}/bookings/${id}`, { method: "DELETE" }, token),
  sync: (token: string, id: string, provider: Provider) => request<{ status: string }>(`${base}/calendar/${id}/sync`, { method: "POST", body: JSON.stringify({ provider }) }, token),
  download: async (token: string, id: string) => {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}${base}/messages/${id}/eml`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("Der Entwurf konnte nicht heruntergeladen werden.");
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "FlintPlate-entwurf.eml"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
