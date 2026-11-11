"use client";

import { request } from "@/lib/api";

const BASE = "/support";

export interface SupportWidgetConfig {
  enabled: boolean;
  allow_video: boolean;
  allow_audio: boolean;
  allow_remote_control: boolean;
  allow_dom_viewing: boolean;
  widget_title: string;
  widget_color: string;
  welcome_message: string | null;
  require_consent: boolean;
}

export interface SupportSession {
  id: string;
  tenant_id: string;
  requester_id: string;
  agent_id: string | null;
  status: string;
  subject: string;
  consent_given: boolean;
  consent_given_at: string | null;
  requested_at: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  video_enabled: boolean;
  audio_enabled: boolean;
  remote_control_enabled: boolean;
  dom_viewing_enabled: boolean;
  billing_model: string;
  billed_amount_cents: number | null;
  summary: string | null;
  end_reason: string | null;
  created_at: string;
  agent_notes?: string | null;
}

// api.ts request signature: (path, options, token?)
export const supportApi = {
  getWidgetConfig: (token: string): Promise<SupportWidgetConfig> =>
    request<SupportWidgetConfig>(`${BASE}/widget-config`, {}, token),

  createSession: (
    token: string,
    data: {
      subject: string;
      video_enabled?: boolean;
      audio_enabled?: boolean;
      remote_control_enabled?: boolean;
      dom_viewing_enabled?: boolean;
    },
  ): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions`, { method: "POST", body: JSON.stringify(data) }, token),

  listSessions: (token: string): Promise<SupportSession[]> =>
    request<SupportSession[]>(`${BASE}/sessions`, {}, token),

  getQueue: (token: string): Promise<SupportSession[]> =>
    request<SupportSession[]>(`${BASE}/sessions/queue`, {}, token),

  getSession: (token: string, sessionId: string): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}`, {}, token),

  acceptSession: (token: string, sessionId: string): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}/accept`, { method: "POST" }, token),

  rejectSession: (token: string, sessionId: string): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}/reject`, { method: "POST" }, token),

  giveConsent: (token: string, sessionId: string): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}/consent`, { method: "POST" }, token),

  endSession: (token: string, sessionId: string): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}/end`, { method: "POST" }, token),

  updateNotes: (
    token: string,
    sessionId: string,
    data: { agent_notes?: string; summary?: string },
  ): Promise<SupportSession> =>
    request<SupportSession>(`${BASE}/sessions/${sessionId}/notes`, { method: "PATCH", body: JSON.stringify(data) }, token),
};
