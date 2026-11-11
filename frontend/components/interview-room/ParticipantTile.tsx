"use client";

import { useEffect, useRef } from "react";
import { MicOff, VideoOff, User } from "lucide-react";

interface Props {
  peerId: string;
  displayName: string;
  stream: MediaStream | null;
  isLocal?: boolean;
  audioMuted: boolean;
  videoMuted: boolean;
}

export function ParticipantTile({ displayName, stream, isLocal, audioMuted, videoMuted }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  return (
    <div className="relative flex flex-col bg-gray-900 rounded-xl overflow-hidden aspect-video">
      {stream && !videoMuted ? (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted={isLocal}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="flex-1 flex items-center justify-center bg-gray-800">
          <div className="flex flex-col items-center gap-2">
            <div className="h-14 w-14 rounded-full bg-gray-700 flex items-center justify-center">
              <User size={28} className="text-gray-400" />
            </div>
          </div>
        </div>
      )}

      {/* Name bar */}
      <div className="absolute bottom-0 left-0 right-0 px-3 py-1.5 bg-gradient-to-t from-black/70 to-transparent flex items-center justify-between">
        <span className="text-white text-xs font-medium truncate">
          {displayName}
          {isLocal && <span className="ml-1 text-white/60">(Du)</span>}
        </span>
        <div className="flex items-center gap-1">
          {audioMuted && <MicOff size={11} className="text-red-400" />}
          {videoMuted && <VideoOff size={11} className="text-red-400" />}
        </div>
      </div>
    </div>
  );
}
