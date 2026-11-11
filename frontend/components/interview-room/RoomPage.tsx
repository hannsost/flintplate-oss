"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { wsClient } from "@/lib/websocket";
import { roomApi, type InterviewRoom, type RoomMessage } from "@/lib/interview-room/api";
import { MeshManager } from "@/lib/interview-room/mesh-webrtc";
import { VideoGrid, type RemotePeer } from "./VideoGrid";
import { ControlBar } from "./ControlBar";
import { ChatSidebar } from "./ChatSidebar";
import { RoomLobby } from "./RoomLobby";

interface Props {
  scheduleId: string;
  /** The URL to navigate back to after leaving */
  backUrl: string;
  isRecruiter: boolean;
}

type Phase = "loading" | "lobby" | "active" | "ended" | "error";

export function RoomPage({ scheduleId, backUrl, isRecruiter }: Props) {
  const router = useRouter();
  const token = auth.getAccess();

  const [phase, setPhase] = useState<Phase>("loading");
  const [room, setRoom] = useState<InterviewRoom | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Media state
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [audioMuted, setAudioMuted] = useState(false);
  const [videoMuted, setVideoMuted] = useState(false);

  // Remote peers
  const [remotePeers, setRemotePeers] = useState<RemotePeer[]>([]);

  // Chat
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<RoomMessage[]>([]);

  const meshRef = useRef<MeshManager | null>(null);
  const roomRef = useRef<InterviewRoom | null>(null);

  // My user id from JWT
  const myUserId = (() => {
    try {
      if (!token) return "";
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.sub as string;
    } catch { return ""; }
  })();

  const myName = (() => {
    try {
      if (!token) return "Ich";
      const payload = JSON.parse(atob(token.split(".")[1]));
      return (payload.name as string) || "Ich";
    } catch { return "Ich"; }
  })();

  // Keep roomRef in sync
  useEffect(() => { roomRef.current = room; }, [room]);

  // ── Load room ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!token) return;
    roomApi.getBySchedule(token, scheduleId)
      .then((r) => { setRoom(r); setPhase("lobby"); })
      .catch((err) => { setErrorMsg(err.message); setPhase("error"); });
  }, [scheduleId, token]);

  // ── WS message handler ─────────────────────────────────────────────────────
  function handleCleanup() {
    meshRef.current?.destroy();
    meshRef.current = null;
    if (room) {
      wsClient.send({ type: "interview.room_leave", room_id: room.id, peer_id: myUserId });
      if (token) roomApi.leaveRoom(token, room.id).catch(() => {});
    }
    localStream?.getTracks().forEach((t) => t.stop());
    setLocalStream(null);
  }

  const handleWsMsg = useCallback(async (msg: Record<string, unknown>) => {
    const r = roomRef.current;
    if (!msg.type || msg.room_id !== r?.id) return;

    const type = msg.type as string;

    if (type === "interview.peer_joined") {
      const peerId = msg.peer_id as string;
      const displayName = msg.display_name as string ?? "Teilnehmer";
      if (peerId === myUserId) return;
      // Add to peer list and start WebRTC
      setRemotePeers((prev) => {
        if (prev.find((p) => p.peerId === peerId)) return prev;
        return [...prev, { peerId, displayName, stream: null, audioMuted: false, videoMuted: false }];
      });
      await meshRef.current?.addPeer(peerId);
      return;
    }

    if (type === "interview.peer_left") {
      const peerId = msg.peer_id as string;
      meshRef.current?.removePeer(peerId);
      setRemotePeers((prev) => prev.filter((p) => p.peerId !== peerId));
      return;
    }

    if (type === "interview.room_ended") {
      handleCleanup();
      setPhase("ended");
      return;
    }

    if (type === "interview.chat_message") {
      setMessages((prev) => [
        ...prev,
        {
          id: (msg.id as string) ?? crypto.randomUUID(),
          sender_id: msg.sender_id as string,
          sender_name: msg.sender_name as string ?? "Unbekannt",
          content: msg.content as string,
          created_at: (msg.created_at as string) ?? new Date().toISOString(),
        },
      ]);
      return;
    }

    if (type === "interview.media_state") {
      const peerId = msg.peer_id as string;
      setRemotePeers((prev) =>
        prev.map((p) =>
          p.peerId === peerId
            ? { ...p, audioMuted: !!(msg.audio_muted), videoMuted: !!(msg.video_muted) }
            : p,
        ),
      );
      return;
    }

    // WebRTC signaling – delegate to MeshManager
    if (
      type === "interview.webrtc_offer" ||
      type === "interview.webrtc_answer" ||
      type === "interview.webrtc_ice"
    ) {
      await meshRef.current?.handleSignal(msg);
      return;
    }
  }, [myUserId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return wsClient.onAny(handleWsMsg);
  }, [handleWsMsg]);

  // ── Join room ──────────────────────────────────────────────────────────────
  async function handleJoin(stream: MediaStream | null, audioEnabled: boolean, videoEnabled: boolean) {
    if (!token || !room) return;
    setLocalStream(stream);
    setAudioMuted(!audioEnabled);
    setVideoMuted(!videoEnabled);

    // REST join
    const joined = await roomApi.joinRoom(token, room.id);
    setRoom(joined);

    // Load chat history
    const history = await roomApi.getMessages(token, room.id).catch(() => []);
    setMessages(history);

    // Setup MeshManager
    const mesh = new MeshManager(
      myUserId,
      room.id,
      (msg) => wsClient.send(msg),
      (peerId, remoteStream) => {
        setRemotePeers((prev) =>
          prev.map((p) => p.peerId === peerId ? { ...p, stream: remoteStream } : p),
        );
      },
      (peerId) => {
        setRemotePeers((prev) => prev.filter((p) => p.peerId !== peerId));
      },
    );
    if (stream) mesh.setLocalStream(stream);
    meshRef.current = mesh;

    // Register in WS room + announce join
    wsClient.whenConnected(() => {
      wsClient.send({
        type: "interview.room_join",
        room_id: room.id,
        display_name: myName,
        peer_id: myUserId,
      });
    });

    // Add existing active participants as peers
    const activePeers = joined.participants.filter(
      (p) => p.user_id !== myUserId && p.joined_at && !p.left_at,
    );
    for (const p of activePeers) {
      setRemotePeers((prev) => {
        if (prev.find((x) => x.peerId === p.user_id)) return prev;
        return [...prev, { peerId: p.user_id, displayName: p.display_name, stream: null, audioMuted: false, videoMuted: false }];
      });
      await mesh.addPeer(p.user_id);
    }

    setPhase("active");
  }

  // ── Media controls ─────────────────────────────────────────────────────────
  function handleToggleAudio() {
    if (!localStream) return;
    const newMuted = !audioMuted;
    localStream.getAudioTracks().forEach((t) => { t.enabled = !newMuted; });
    setAudioMuted(newMuted);
    broadcastMediaState(!newMuted, !videoMuted);
  }

  function handleToggleVideo() {
    if (!localStream) return;
    const newMuted = !videoMuted;
    localStream.getVideoTracks().forEach((t) => { t.enabled = !newMuted; });
    setVideoMuted(newMuted);
    broadcastMediaState(!audioMuted, !newMuted);
  }

  function broadcastMediaState(audioEnabled: boolean, videoEnabled: boolean) {
    if (!room) return;
    wsClient.send({
      type: "interview.media_state",
      room_id: room.id,
      peer_id: myUserId,
      audio_muted: !audioEnabled,
      video_muted: !videoEnabled,
    });
  }

  // ── Chat ───────────────────────────────────────────────────────────────────
  async function handleSendMessage(content: string) {
    if (!token || !room) return;
    // Persist to DB
    const msg = await roomApi.sendMessage(token, room.id, content).catch(() => null);
    if (msg) {
      // Also broadcast via WS so others see it in real-time
      wsClient.send({
        type: "interview.chat_message",
        room_id: room.id,
        id: msg.id,
        sender_id: msg.sender_id,
        sender_name: msg.sender_name,
        content: msg.content,
        created_at: msg.created_at,
      });
    }
  }

  // ── Leave / End ────────────────────────────────────────────────────────────


  async function handleLeave() {
    handleCleanup();
    router.push(backUrl);
  }

  async function handleEndRoom() {
    if (!token || !room) return;
    wsClient.send({ type: "interview.room_ended", room_id: room.id });
    await roomApi.endRoom(token, room.id).catch(() => {});
    handleCleanup();
    router.push(backUrl);
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (phase === "loading") {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center bg-gray-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center bg-gray-950 text-center px-6">
        <div className="space-y-3">
          <p className="text-red-400 font-medium">{errorMsg ?? "Fehler beim Laden des Raums."}</p>
          <button
            onClick={() => router.push(backUrl)}
            className="text-sm text-gray-400 hover:text-white underline"
          >
            Zurück
          </button>
        </div>
      </div>
    );
  }

  if (phase === "ended") {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center bg-gray-950 text-center px-6">
        <div className="space-y-3">
          <p className="text-lg font-semibold text-white">Sitzung beendet</p>
          <p className="text-sm text-gray-400">Das Interview wurde beendet.</p>
          <button
            onClick={() => router.push(backUrl)}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            Zurück
          </button>
        </div>
      </div>
    );
  }

  if (phase === "lobby" && room) {
    return <RoomLobby room={room} onJoin={handleJoin} />;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)] bg-gray-950 overflow-hidden">
      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Video grid */}
        <div className="flex-1 overflow-hidden">
          <VideoGrid
            localStream={localStream}
            localName={myName}
            localAudioMuted={audioMuted}
            localVideoMuted={videoMuted}
            remotePeers={remotePeers}
          />
        </div>

        {/* Chat sidebar */}
        {chatOpen && (
          <ChatSidebar
            messages={messages}
            myUserId={myUserId}
            onSend={handleSendMessage}
            onClose={() => setChatOpen(false)}
          />
        )}
      </div>

      {/* Control bar */}
      <ControlBar
        audioMuted={audioMuted}
        videoMuted={videoMuted}
        chatOpen={chatOpen}
        participantCount={remotePeers.length + 1}
        onToggleAudio={handleToggleAudio}
        onToggleVideo={handleToggleVideo}
        onToggleChat={() => setChatOpen((v) => !v)}
        onLeave={handleLeave}
        isRecruiter={isRecruiter}
        onEndRoom={isRecruiter ? handleEndRoom : undefined}
      />
    </div>
  );
}
