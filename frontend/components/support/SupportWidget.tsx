"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Headphones, X, Video, Mic, Monitor, MousePointer, ChevronRight, AlertCircle } from "lucide-react";
import { auth } from "@/lib/auth";
import { wsClient } from "@/lib/websocket";
import { supportApi, SupportSession, SupportWidgetConfig } from "@/lib/support/api";
import {
  createPeerConnection,
  createOffer,
  handleAnswer,
  addIceCandidate,
  getUserMedia,
} from "@/lib/support/webrtc";
import {
  simulateMouseEvent,
  simulateKeyboardEvent,
  mountAgentCursor,
  unmountAgentCursor,
  RemoteMouseEvent,
  RemoteKeyboardEvent,
} from "@/lib/support/remote-control";

type Phase = "idle" | "config_loading" | "request_form" | "consent" | "waiting" | "active" | "ended";

export function SupportWidget() {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [config, setConfig] = useState<SupportWidgetConfig | null>(null);
  const [session, setSession] = useState<SupportSession | null>(null);
  const [subject, setSubject] = useState("");
  const [wantVideo, setWantVideo] = useState(false);
  const [wantAudio, setWantAudio] = useState(false);
  const [wantRemote, setWantRemote] = useState(false);
  const [wantDom, setWantDom] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentName, setAgentName] = useState("Support");

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteVideoRef = useRef<HTMLVideoElement | null>(null);
  const rrwebStopRef = useRef<(() => void) | null>(null);
  const sessionRef = useRef<SupportSession | null>(null);
  const agentNameRef = useRef("Support");

  // Keep sessionRef in sync
  useEffect(() => { sessionRef.current = session; }, [session]);

  const token = auth.getAccess();

  // ── Load widget config on first open ──────────────────────────────────────
  useEffect(() => {
    if (!open || config || !token) return;
    setPhase("config_loading");
    supportApi.getWidgetConfig(token)
      .then((cfg) => {
        setConfig(cfg);
        setPhase(cfg.enabled ? "request_form" : "idle");
        setWantVideo(cfg.allow_video);
        setWantAudio(cfg.allow_audio);
        setWantRemote(cfg.allow_remote_control);
        setWantDom(cfg.allow_dom_viewing);
      })
      .catch(() => {
        setConfig({ enabled: true, allow_video: true, allow_audio: true, allow_remote_control: true, allow_dom_viewing: true, widget_title: "Live Support", widget_color: "#2563eb", welcome_message: null, require_consent: true });
        setPhase("request_form");
      });
  }, [open, config, token]);

  // ── WS message handler ────────────────────────────────────────────────────
  const handleMsg = useCallback(async (msg: Record<string, unknown>) => {
    const s = sessionRef.current;
    if (!msg.type || msg.session_id !== s?.id) return;

    if (msg.type === "support.accepted") {
      const name = (msg.agent_name as string) || "Support";
      setAgentName(name);
      agentNameRef.current = name;
      setPhase("active");
      // Don't start recording yet – wait for agent_ready so the WS peer map is established
      return;
    }

    if (msg.type === "support.agent_ready") {
      // Defensive: ensure phase is active even if support.accepted was dropped
      setAgentName(agentNameRef.current);
      setPhase("active");
      if (s) await startSession(agentNameRef.current, s);
      return;
    }
    if (msg.type === "support.rejected") {
      setError("Kein Agent verfügbar. Bitte später erneut versuchen.");
      setPhase("request_form");
      return;
    }
    if (msg.type === "support.ended") {
      cleanup();
      setPhase("ended");
      return;
    }

    if (!pcRef.current || !s) return;
    if (msg.type === "support.webrtc_answer") {
      await handleAnswer(pcRef.current, msg.sdp as RTCSessionDescriptionInit);
    } else if (msg.type === "support.webrtc_ice") {
      await addIceCandidate(pcRef.current, msg.candidate as RTCIceCandidateInit);
    } else if (msg.type === "support.control_mouse") {
      simulateMouseEvent(msg as unknown as RemoteMouseEvent);
    } else if (msg.type === "support.control_keyboard") {
      simulateKeyboardEvent(msg as unknown as RemoteKeyboardEvent);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return wsClient.onAny(handleMsg);
  }, [handleMsg]);

  // ── Send via WS ────────────────────────────────────────────────────────────
  function send(msg: Record<string, unknown>) {
    wsClient.send(msg);
  }

  // ── Request session ────────────────────────────────────────────────────────
  async function handleRequestSupport() {
    if (!token || !subject.trim()) return;
    setError(null);
    try {
      const s = await supportApi.createSession(token, {
        subject: subject.trim(),
        video_enabled: wantVideo,
        audio_enabled: wantAudio,
        remote_control_enabled: wantRemote,
        dom_viewing_enabled: wantDom,
      });
      setSession(s);
      send({ type: "support.session_join", session_id: s.id, peer_role: "requester" });
      setPhase(config?.require_consent ? "consent" : "waiting");
    } catch {
      setError("Support-Anfrage konnte nicht erstellt werden.");
    }
  }

  // ── Give consent ───────────────────────────────────────────────────────────
  async function handleConsent() {
    if (!token || !session) return;
    await supportApi.giveConsent(token, session.id);
    setPhase("waiting");
  }

  // ── Start active session ───────────────────────────────────────────────────
  async function startSession(aName: string, s: SupportSession) {
    mountAgentCursor(aName);

    if (s.dom_viewing_enabled) {
      try {
        const rrweb = await import("rrweb");
        let first = true;
        const stop = rrweb.record({
          emit(event) {
            send({ type: first ? "support.dom_snapshot" : "support.dom_events", session_id: s.id, events: [event] });
            first = false;
          },
          maskInputOptions: { password: true },
          blockClass: "rr-block",
          ignoreClass: "rr-ignore",
          recordCanvas: false,
        });
        rrwebStopRef.current = stop ?? null;
      } catch { /* rrweb not available */ }
    }

    if (s.audio_enabled || s.video_enabled) {
      const stream = await getUserMedia(s.video_enabled, s.audio_enabled);
      if (stream) {
        localStreamRef.current = stream;
        const pc = await createPeerConnection(s.id, (m) => send(m as Record<string, unknown>), (rs) => {
          if (remoteVideoRef.current) remoteVideoRef.current.srcObject = rs;
        });
        stream.getTracks().forEach((t) => pc.addTrack(t, stream));
        pcRef.current = pc;
        await createOffer(pc, s.id, (m) => send(m as Record<string, unknown>));
      }
    }
  }

  // ── End session ────────────────────────────────────────────────────────────
  async function handleEndSession() {
    if (!token || !session) return;
    await supportApi.endSession(token, session.id);
    cleanup();
    setPhase("ended");
  }

  function cleanup() {
    rrwebStopRef.current?.();
    rrwebStopRef.current = null;
    localStreamRef.current?.getTracks().forEach((t) => t.stop());
    localStreamRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    unmountAgentCursor();
  }

  function handleClose() {
    if (phase === "active") handleEndSession();
    setOpen(false);
    setPhase("idle");
    setSession(null);
    setError(null);
    cleanup();
  }

  const widgetColor = config?.widget_color ?? "#2563eb";

  return (
    <>
      {/* Floating trigger – below FeedbackWidget */}
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-3 z-40 flex h-11 w-11 items-center justify-center gap-1.5 rounded-full text-sm font-medium text-white shadow-lg hover:opacity-90 transition-opacity sm:bottom-5 sm:right-5 sm:h-auto sm:w-[7.5rem] sm:px-3 sm:py-2"
        style={{ backgroundColor: widgetColor }}
        aria-label="Support anfordern"
      >
        <Headphones size={14} />
        <span className="hidden sm:inline">{phase === "waiting" ? "Warte..." : phase === "active" ? "Live" : "Support"}</span>
        {phase === "active" && <span className="ml-1 h-2 w-2 rounded-full bg-green-400 animate-pulse" />}
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-3 z-50 w-[calc(100vw-1.5rem)] max-w-80 rounded-2xl border border-gray-200 bg-white shadow-2xl overflow-hidden sm:bottom-16 sm:right-5">
          <div className="px-4 py-3 flex items-center justify-between" style={{ backgroundColor: widgetColor }}>
            <span className="text-sm font-semibold text-white flex items-center gap-2">
              <Headphones size={14} />
              {config?.widget_title ?? "Live Support"}
            </span>
            <button onClick={handleClose} className="text-white/70 hover:text-white transition-colors">
              <X size={16} />
            </button>
          </div>

          <div className="p-4">
            {phase === "config_loading" && (
              <div className="flex justify-center py-6">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
              </div>
            )}

            {phase === "request_form" && (
              <div className="space-y-3">
                {config?.welcome_message && <p className="text-sm text-gray-600">{config.welcome_message}</p>}
                {error && (
                  <div className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
                    <AlertCircle size={12} /> {error}
                  </div>
                )}
                <div>
                  <label className="text-xs font-medium text-gray-700 mb-1 block">Womit können wir helfen?</label>
                  <textarea
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="Kurze Beschreibung des Problems…"
                    rows={3}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  />
                </div>
                <div className="space-y-1.5">
                  {config?.allow_audio && (
                    <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                      <input type="checkbox" checked={wantAudio} onChange={(e) => setWantAudio(e.target.checked)} className="rounded" />
                      <Mic size={12} /> Mikrofon freigeben
                    </label>
                  )}
                  {config?.allow_video && (
                    <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                      <input type="checkbox" checked={wantVideo} onChange={(e) => setWantVideo(e.target.checked)} className="rounded" />
                      <Video size={12} /> Kamera freigeben
                    </label>
                  )}
                  {config?.allow_dom_viewing && (
                    <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                      <input type="checkbox" checked={wantDom} onChange={(e) => setWantDom(e.target.checked)} className="rounded" />
                      <Monitor size={12} /> Bildschirm teilen (DOM)
                    </label>
                  )}
                  {config?.allow_remote_control && (
                    <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                      <input type="checkbox" checked={wantRemote} onChange={(e) => setWantRemote(e.target.checked)} className="rounded" />
                      <MousePointer size={12} /> Fernsteuerung erlauben
                    </label>
                  )}
                </div>
                <button
                  onClick={handleRequestSupport}
                  disabled={!subject.trim()}
                  className="w-full rounded-lg py-2 text-sm font-medium text-white transition-colors disabled:opacity-40"
                  style={{ backgroundColor: widgetColor }}
                >
                  Support anfordern <ChevronRight size={14} className="inline" />
                </button>
              </div>
            )}

            {phase === "consent" && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-gray-900">Datenschutz-Einwilligung</p>
                <p className="text-xs text-gray-600 leading-relaxed">
                  Für die Support-Sitzung kann unser Support-Team Ihre Bildschirmansicht sehen
                  und mit Ihnen sprechen. Passwörter und markierte Felder werden automatisch
                  ausgeblendet. Die Session-Dauer wird gespeichert. Sie können die Sitzung
                  jederzeit beenden.
                </p>
                <div className="flex gap-2">
                  <button onClick={handleConsent} className="flex-1 rounded-lg py-2 text-sm font-medium text-white" style={{ backgroundColor: widgetColor }}>
                    Zustimmen &amp; fortfahren
                  </button>
                  <button onClick={handleClose} className="flex-1 rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50">
                    Ablehnen
                  </button>
                </div>
              </div>
            )}

            {phase === "waiting" && (
              <div className="py-4 text-center space-y-3">
                <div className="flex justify-center">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent" style={{ borderColor: widgetColor }} />
                </div>
                <p className="text-sm font-medium text-gray-900">Warten auf Support-Agent…</p>
                <p className="text-xs text-gray-500">Ein Agent wird sich gleich verbinden.</p>
                <button onClick={handleClose} className="text-xs text-gray-400 hover:text-gray-600 underline">Anfrage abbrechen</button>
              </div>
            )}

            {phase === "active" && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-green-500 animate-pulse" />
                  <span className="text-sm font-medium text-gray-900">Verbunden mit {agentName}</span>
                </div>
                {(session?.video_enabled || session?.audio_enabled) && (
                  <video ref={remoteVideoRef} autoPlay playsInline className="w-full rounded-lg bg-black aspect-video" />
                )}
                <p className="text-xs text-gray-500">
                  {session?.dom_viewing_enabled && "Bildschirm wird geteilt. "}
                  {session?.remote_control_enabled && "Fernsteuerung aktiv."}
                </p>
                <button onClick={handleEndSession} className="w-full rounded-lg border border-red-200 bg-red-50 py-2 text-sm font-medium text-red-700 hover:bg-red-100">
                  Sitzung beenden
                </button>
              </div>
            )}

            {phase === "ended" && (
              <div className="py-4 text-center space-y-2">
                <p className="text-sm font-medium text-gray-900">Sitzung beendet</p>
                <p className="text-xs text-gray-500">Vielen Dank – wir hoffen, wir konnten helfen!</p>
                <button onClick={() => { setPhase("request_form"); setSession(null); setError(null); }} className="text-xs underline" style={{ color: widgetColor }}>
                  Neue Anfrage stellen
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
