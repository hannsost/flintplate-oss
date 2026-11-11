"use client";

import { useEffect, useRef, useState } from "react";
import { Video, VideoOff, Mic, MicOff, Users } from "lucide-react";
import type { InterviewRoom } from "@/lib/interview-room/api";

interface Props {
  room: InterviewRoom;
  onJoin: (stream: MediaStream | null, audioEnabled: boolean, videoEnabled: boolean) => void;
}

export function RoomLobby({ room, onJoin }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [videoOn, setVideoOn] = useState(true);
  const [audioOn, setAudioOn] = useState(true);
  const [loading, setLoading] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    navigator.mediaDevices
      .getUserMedia({ video: true, audio: true })
      .then((s) => {
        if (!active) { s.getTracks().forEach((t) => t.stop()); return; }
        setStream(s);
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => setMediaError("Kamera/Mikrofon nicht verfügbar. Sie können trotzdem beitreten."));
    return () => {
      active = false;
    };
  }, []);

  function toggleVideo() {
    stream?.getVideoTracks().forEach((t) => { t.enabled = !videoOn; });
    setVideoOn((v) => !v);
  }

  function toggleAudio() {
    stream?.getAudioTracks().forEach((t) => { t.enabled = !audioOn; });
    setAudioOn((a) => !a);
  }

  function handleJoin() {
    setLoading(true);
    // Apply mute state before handing stream to RoomPage
    if (stream) {
      stream.getVideoTracks().forEach((t) => { t.enabled = videoOn; });
      stream.getAudioTracks().forEach((t) => { t.enabled = audioOn; });
    }
    onJoin(stream, audioOn, videoOn);
  }

  const activeCount = room.participants.filter((p) => p.joined_at && !p.left_at).length;

  return (
    <div className="flex items-center justify-center h-[calc(100vh-3.5rem)] bg-gray-950 p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-xl font-bold text-white">{room.title}</h1>
          <p className="text-sm text-gray-400 flex items-center justify-center gap-1.5">
            <Users size={13} />
            {activeCount > 0 ? `${activeCount} Teilnehmer bereits im Raum` : "Warte auf Teilnehmer"}
          </p>
        </div>

        {/* Camera preview */}
        <div className="relative rounded-2xl overflow-hidden bg-gray-900 aspect-video">
          {stream && videoOn ? (
            <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center">
              <VideoOff size={36} className="text-gray-600" />
            </div>
          )}
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-3">
            <button
              onClick={toggleAudio}
              className={`rounded-full p-2.5 ${audioOn ? "bg-gray-700 text-white" : "bg-red-600 text-white"}`}
            >
              {audioOn ? <Mic size={16} /> : <MicOff size={16} />}
            </button>
            <button
              onClick={toggleVideo}
              className={`rounded-full p-2.5 ${videoOn ? "bg-gray-700 text-white" : "bg-red-600 text-white"}`}
            >
              {videoOn ? <Video size={16} /> : <VideoOff size={16} />}
            </button>
          </div>
        </div>

        {mediaError && (
          <p className="text-xs text-amber-400 text-center">{mediaError}</p>
        )}

        <button
          onClick={handleJoin}
          disabled={loading}
          className="w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          {loading ? "Verbinde…" : "Jetzt beitreten"}
        </button>
      </div>
    </div>
  );
}
