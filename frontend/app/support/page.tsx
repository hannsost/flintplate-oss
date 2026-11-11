"use client";

export const dynamic = "force-dynamic";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Headphones, Clock, User, Monitor, Mic, Video, MousePointer,
  CheckCircle, XCircle, PlayCircle,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { supportApi, SupportSession } from "@/lib/support/api";
import { wsClient } from "@/lib/websocket";

const STATUS_LABEL: Record<string, string> = {
  pending: "Wartet",
  active: "Aktiv",
  ended: "Beendet",
  rejected: "Abgelehnt",
  cancelled: "Abgebrochen",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  active: "bg-green-100 text-green-700",
  ended: "bg-gray-100 text-gray-600",
  rejected: "bg-red-100 text-red-700",
  cancelled: "bg-gray-100 text-gray-500",
};

function duration(s: SupportSession): string {
  if (!s.started_at) return "—";
  const start = new Date(s.started_at);
  const end = s.ended_at ? new Date(s.ended_at) : new Date();
  const secs = Math.floor((end.getTime() - start.getTime()) / 1000);
  const m = Math.floor(secs / 60), sec = secs % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function SupportQueuePage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SupportSession[]>([]);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? auth.getAccess() : null;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const queue = await supportApi.getQueue(token);
      setSessions(queue);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  // Live updates via WS
  useEffect(() => {
    return wsClient.onAny((msg) => {
      if (msg.type === "support.incoming") {
        load();
      } else if (msg.type === "support.ended" || msg.type === "support.accepted") {
        setSessions((prev) =>
          prev.map((s) => s.id === msg.session_id
            ? { ...s, status: msg.type === "support.ended" ? "ended" : "active" }
            : s
          ).filter((s) => (s.status as string) !== "ended")
        );
      }
    });
  }, [load]);

  async function handleAccept(sessionId: string) {
    if (!token) return;
    await supportApi.acceptSession(token, sessionId);
    router.push(`/support/session/${sessionId}`);
  }

  async function handleReject(sessionId: string) {
    if (!token) return;
    await supportApi.rejectSession(token, sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
  }

  const pending = sessions.filter((s) => s.status === "pending");
  const active = sessions.filter((s) => s.status === "active");

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Support Queue</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {pending.length} wartend · {active.length} aktiv
          </p>
        </div>
        <button onClick={load} className="text-sm text-blue-600 hover:underline">
          Aktualisieren
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Pending sessions */}
          {pending.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Neue Anfragen</h2>
              {pending.map((s) => (
                <div key={s.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[s.status]}`}>
                        {STATUS_LABEL[s.status]}
                      </span>
                      <span className="text-xs text-gray-400 flex items-center gap-1">
                        <Clock size={10} />
                        {new Date(s.requested_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-gray-900 truncate">{s.subject}</p>
                    <div className="flex items-center gap-3 mt-1.5">
                      {s.audio_enabled && <span className="flex items-center gap-1 text-xs text-gray-500"><Mic size={10} /> Audio</span>}
                      {s.video_enabled && <span className="flex items-center gap-1 text-xs text-gray-500"><Video size={10} /> Video</span>}
                      {s.dom_viewing_enabled && <span className="flex items-center gap-1 text-xs text-gray-500"><Monitor size={10} /> DOM</span>}
                      {s.remote_control_enabled && <span className="flex items-center gap-1 text-xs text-gray-500"><MousePointer size={10} /> Control</span>}
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={() => handleReject(s.id)}
                      className="flex items-center gap-1 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50"
                    >
                      <XCircle size={13} /> Ablehnen
                    </button>
                    <button
                      onClick={() => handleAccept(s.id)}
                      className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                    >
                      <PlayCircle size={13} /> Annehmen
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* Active sessions */}
          {active.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Aktive Sitzungen</h2>
              {active.map((s) => (
                <div key={s.id} className="rounded-xl border border-green-200 bg-green-50 p-4 flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLOR[s.status]}`}>
                        {STATUS_LABEL[s.status]}
                      </span>
                      <span className="text-xs text-gray-400 flex items-center gap-1">
                        <Clock size={10} /> {duration(s)}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-gray-900 truncate">{s.subject}</p>
                  </div>
                  <button
                    onClick={() => router.push(`/support/session/${s.id}`)}
                    className="flex items-center gap-1 rounded-lg bg-green-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-800 shrink-0"
                  >
                    <Monitor size={13} /> Öffnen
                  </button>
                </div>
              ))}
            </section>
          )}

          {pending.length === 0 && active.length === 0 && (
            <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center">
              <Headphones size={32} className="mx-auto mb-3 text-gray-300" />
              <p className="text-sm text-gray-500">Keine offenen Support-Anfragen.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
