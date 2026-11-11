"use client";

export const dynamic = "force-dynamic";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamicImport from "next/dynamic";
import {
  Monitor, Mic, Video, MousePointer, PhoneOff, Save,
  ChevronLeft, Maximize2, Minimize2,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { supportApi, SupportSession } from "@/lib/support/api";
import { wsClient } from "@/lib/websocket";
import {
  createPeerConnection,
  handleOffer,
  handleAnswer,
  addIceCandidate,
  getUserMedia,
} from "@/lib/support/webrtc";

// Dynamically import rrweb replayer (client-only, heavy)
const RRWebReplayer = dynamicImport(() => import("@/components/support/RRWebReplayer"), { ssr: false });

export default function AgentSessionPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const router = useRouter();
  const token = typeof window !== "undefined" ? auth.getAccess() : null;

  const [session, setSession] = useState<SupportSession | null>(null);
  const [notes, setNotes] = useState("");
  const [savedNotes, setSavedNotes] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [domEvents, setDomEvents] = useState<unknown[]>([]);
  const [fullscreen, setFullscreen] = useState(false);

  // Remote control state
  const [controlEnabled, setControlEnabled] = useState(false);
  const replayerContainerRef = useRef<HTMLDivElement>(null);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteVideoRef = useRef<HTMLVideoElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<SupportSession | null>(null);

  // Keep sessionRef in sync so callbacks always see latest session
  useEffect(() => { sessionRef.current = session; }, [session]);

  function sendSignal(msg: Record<string, unknown>) {
    wsClient.send(msg);
  }

  // ── Load session ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!token || !sessionId) return;
    supportApi.getSession(token, sessionId).then((s) => {
      setSession(s);
      setNotes(s.agent_notes ?? "");
      // Ensure WS is open before registering – the layout starts connecting synchronously
      // but the handshake may still be in progress when getSession() resolves.
      wsClient.whenConnected(() => {
        sendSignal({ type: "support.session_join", session_id: sessionId, peer_role: "agent" });
        sendSignal({ type: "support.agent_ready", session_id: sessionId });
      });
    }).catch(() => router.push("/support"));
  }, [token, sessionId, router]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Timer ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (session?.started_at) {
      timerRef.current = setInterval(() => {
        const start = new Date(session.started_at!).getTime();
        setElapsed(Math.floor((Date.now() - start) / 1000));
      }, 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [session?.started_at]);

  function cleanup() {
    localStreamRef.current?.getTracks().forEach((t) => t.stop());
    localStreamRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    if (timerRef.current) clearInterval(timerRef.current);
  }

  // ── WS message handler ────────────────────────────────────────────────────
  const handleWsMessage = useCallback(async (msg: Record<string, unknown>) => {
    if (!msg.type || msg.session_id !== sessionId) return;

    if (msg.type === "support.ended") {
      cleanup();
      router.push("/support");
      return;
    }

    // DOM events from rrweb
    if (msg.type === "support.dom_snapshot") {
      setDomEvents((msg.events as unknown[]) ?? []);
    } else if (msg.type === "support.dom_events") {
      setDomEvents((prev) => [...prev, ...((msg.events as unknown[]) ?? [])]);
    }

    // WebRTC signaling
    if (msg.type === "support.webrtc_offer") {
      const pc = await createPeerConnection(
        sessionId,
        sendSignal,
        (stream) => { if (remoteVideoRef.current) remoteVideoRef.current.srcObject = stream; },
      );
      // Add agent's own camera/mic tracks so the requester can see/hear the agent
      const s = sessionRef.current;
      if (s?.video_enabled || s?.audio_enabled) {
        const stream = await getUserMedia(s.video_enabled, s.audio_enabled);
        if (stream) {
          localStreamRef.current = stream;
          stream.getTracks().forEach((t) => pc.addTrack(t, stream));
        }
      }
      pcRef.current = pc;
      await handleOffer(pc, sessionId, msg.sdp as RTCSessionDescriptionInit, sendSignal);
    } else if (msg.type === "support.webrtc_answer") {
      if (pcRef.current) await handleAnswer(pcRef.current, msg.sdp as RTCSessionDescriptionInit);
    } else if (msg.type === "support.webrtc_ice") {
      if (pcRef.current) await addIceCandidate(pcRef.current, msg.candidate as RTCIceCandidateInit);
    }
  }, [sessionId, router]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return wsClient.onAny((msg) => { handleWsMessage(msg); });
  }, [handleWsMessage]);

  // ── Remote control: forward mouse events from replayer overlay ─────────
  function handleRemoteMouseEvent(
    action: "move" | "click" | "dblclick" | "scroll" | "mousedown" | "mouseup",
    nx: number,
    ny: number,
    extra?: { deltaX?: number; deltaY?: number },
  ) {
    if (!controlEnabled) return;
    sendSignal({
      type: "support.control_mouse",
      session_id: sessionId,
      x: nx,
      y: ny,
      action,
      ...extra,
    });
  }

  function handleRemoteKeyEvent(key: string, code: string, action: "keydown" | "keyup") {
    if (!controlEnabled) return;
    sendSignal({ type: "support.control_keyboard", session_id: sessionId, key, code, action });
  }

  // ── End session ───────────────────────────────────────────────────────────
  async function handleEnd() {
    if (!token) return;
    await supportApi.endSession(token, sessionId);
    cleanup();
    router.push("/support");
  }

  async function handleSaveNotes() {
    if (!token) return;
    await supportApi.updateNotes(token, sessionId, { agent_notes: notes });
    setSavedNotes(true);
    setTimeout(() => setSavedNotes(false), 2500);
  }



  const elapsedStr = `${Math.floor(elapsed / 60)}:${(elapsed % 60).toString().padStart(2, "0")}`;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Main viewer */}
      <div className={`flex-1 flex flex-col bg-gray-950 relative ${fullscreen ? "fixed inset-0 z-50" : ""}`}>
        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2 bg-gray-900 text-white text-sm">
          <div className="flex items-center gap-3">
            <button onClick={() => router.push("/support")} className="text-gray-400 hover:text-white">
              <ChevronLeft size={16} />
            </button>
            <span className="font-mono text-green-400">{elapsedStr}</span>
            <span className="text-gray-300 truncate max-w-xs">{session?.subject}</span>
            {session?.dom_viewing_enabled && (
              <span className="font-mono text-xs text-gray-500">DOM:{domEvents.length}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {session?.dom_viewing_enabled && (
              <button
                onClick={() => setControlEnabled((v) => !v)}
                className={`flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors ${controlEnabled ? "bg-blue-600 text-white" : "bg-gray-700 text-gray-300 hover:bg-gray-600"}`}
              >
                <MousePointer size={12} />
                {controlEnabled ? "Control aktiv" : "Control"}
              </button>
            )}
            <button onClick={() => setFullscreen((v) => !v)} className="p-1 text-gray-400 hover:text-white">
              {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button
              onClick={handleEnd}
              className="flex items-center gap-1 rounded bg-red-700 px-3 py-1 text-xs font-medium text-white hover:bg-red-600"
            >
              <PhoneOff size={12} /> Beenden
            </button>
          </div>
        </div>

        {/* DOM replayer */}
        <div className="flex-1 overflow-hidden relative" ref={replayerContainerRef}>
          {session?.dom_viewing_enabled && domEvents.length > 0 ? (
            <RRWebReplayer
              events={domEvents}
              controlEnabled={controlEnabled}
              onMouseEvent={handleRemoteMouseEvent}
              onKeyEvent={handleRemoteKeyEvent}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-gray-600">
              {session?.dom_viewing_enabled
                ? <div className="text-center"><Monitor size={40} className="mx-auto mb-3 text-gray-700" /><p className="text-sm">Warte auf DOM-Daten…</p></div>
                : <div className="text-center"><Monitor size={40} className="mx-auto mb-3 text-gray-700" /><p className="text-sm">DOM-Ansicht nicht aktiviert</p></div>
              }
            </div>
          )}
        </div>

        {/* Remote video (audio/video call) */}
        {(session?.video_enabled || session?.audio_enabled) && (
          <div className="absolute bottom-16 right-4 w-48">
            <video ref={remoteVideoRef} autoPlay playsInline className="rounded-lg shadow-xl bg-black w-full" />
          </div>
        )}
      </div>

      {/* Sidebar */}
      {!fullscreen && (
        <aside className="w-72 border-l border-gray-200 bg-white flex flex-col">
          {/* Session info */}
          <div className="p-4 border-b border-gray-100 space-y-2">
            <h3 className="text-sm font-semibold text-gray-900">Session-Details</h3>
            <div className="grid grid-cols-2 gap-1 text-xs text-gray-600">
              {session?.audio_enabled && <span className="flex items-center gap-1"><Mic size={10} /> Audio</span>}
              {session?.video_enabled && <span className="flex items-center gap-1"><Video size={10} /> Video</span>}
              {session?.dom_viewing_enabled && <span className="flex items-center gap-1"><Monitor size={10} /> DOM</span>}
              {session?.remote_control_enabled && <span className="flex items-center gap-1"><MousePointer size={10} /> Control</span>}
            </div>
            <p className="text-xs text-gray-500">
              Billing: <span className="font-medium">{session?.billing_model}</span>
            </p>
          </div>

          {/* Agent notes */}
          <div className="flex-1 p-4 flex flex-col gap-2">
            <label className="text-xs font-medium text-gray-700">
              Interne Notizen (nicht sichtbar für Kunden)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={8}
              placeholder="Session-Verlauf, Lösungsschritte…"
              className="flex-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
            <button
              onClick={handleSaveNotes}
              className="flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 py-2 text-xs font-medium text-white hover:bg-blue-700"
            >
              <Save size={12} />
              {savedNotes ? "Gespeichert ✓" : "Notizen speichern"}
            </button>
          </div>
        </aside>
      )}
    </div>
  );
}
