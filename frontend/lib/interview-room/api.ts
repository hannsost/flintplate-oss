"use client";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface RoomParticipant {
  id: string;
  user_id: string;
  display_name: string;
  role: "recruiter" | "candidate" | "observer";
  joined_at: string | null;
  left_at: string | null;
}

export interface InterviewRoom {
  id: string;
  schedule_id: string;
  title: string;
  status: "waiting" | "active" | "ended";
  started_at: string | null;
  ended_at: string | null;
  participants: RoomParticipant[];
  created_at: string;
}

export interface RoomMessage {
  id: string;
  sender_id: string | null;
  sender_name: string;
  content: string;
  created_at: string;
}

function headers(token: string) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

async function request<T>(token: string, path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...options, headers: headers(token) });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const roomApi = {
  getBySchedule: (token: string, scheduleId: string): Promise<InterviewRoom> =>
    request(token, `/interview-rooms/by-schedule/${scheduleId}`),

  getRoom: (token: string, roomId: string): Promise<InterviewRoom> =>
    request(token, `/interview-rooms/${roomId}`),

  joinRoom: (token: string, roomId: string): Promise<InterviewRoom> =>
    request(token, `/interview-rooms/${roomId}/join`, { method: "POST" }),

  leaveRoom: (token: string, roomId: string): Promise<void> =>
    request(token, `/interview-rooms/${roomId}/leave`, { method: "POST" }),

  endRoom: (token: string, roomId: string): Promise<InterviewRoom> =>
    request(token, `/interview-rooms/${roomId}/end`, { method: "POST" }),

  getMessages: (token: string, roomId: string): Promise<RoomMessage[]> =>
    request(token, `/interview-rooms/${roomId}/messages`),

  sendMessage: (token: string, roomId: string, content: string): Promise<RoomMessage> =>
    request(token, `/interview-rooms/${roomId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};
