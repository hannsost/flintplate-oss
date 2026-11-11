"use client";

import { Mic, MicOff, Video, VideoOff, PhoneOff, MessageSquare, Users } from "lucide-react";

interface Props {
  audioMuted: boolean;
  videoMuted: boolean;
  chatOpen: boolean;
  participantCount: number;
  onToggleAudio: () => void;
  onToggleVideo: () => void;
  onToggleChat: () => void;
  onLeave: () => void;
  isRecruiter: boolean;
  onEndRoom?: () => void;
}

export function ControlBar({
  audioMuted,
  videoMuted,
  chatOpen,
  participantCount,
  onToggleAudio,
  onToggleVideo,
  onToggleChat,
  onLeave,
  isRecruiter,
  onEndRoom,
}: Props) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-3 bg-gray-900 border-t border-gray-800">
      {/* Participants count */}
      <div className="flex items-center gap-1.5 text-gray-400 text-xs mr-2">
        <Users size={14} />
        <span>{participantCount}</span>
      </div>

      <button
        onClick={onToggleAudio}
        className={`flex flex-col items-center gap-0.5 rounded-full p-3 transition-colors ${
          audioMuted ? "bg-red-600 text-white" : "bg-gray-700 text-white hover:bg-gray-600"
        }`}
        title={audioMuted ? "Mikrofon einschalten" : "Mikrofon ausschalten"}
      >
        {audioMuted ? <MicOff size={18} /> : <Mic size={18} />}
      </button>

      <button
        onClick={onToggleVideo}
        className={`flex flex-col items-center gap-0.5 rounded-full p-3 transition-colors ${
          videoMuted ? "bg-red-600 text-white" : "bg-gray-700 text-white hover:bg-gray-600"
        }`}
        title={videoMuted ? "Kamera einschalten" : "Kamera ausschalten"}
      >
        {videoMuted ? <VideoOff size={18} /> : <Video size={18} />}
      </button>

      <button
        onClick={onToggleChat}
        className={`flex flex-col items-center gap-0.5 rounded-full p-3 transition-colors ${
          chatOpen ? "bg-blue-600 text-white" : "bg-gray-700 text-white hover:bg-gray-600"
        }`}
        title="Chat"
      >
        <MessageSquare size={18} />
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {isRecruiter && onEndRoom && (
        <button
          onClick={onEndRoom}
          className="flex items-center gap-2 rounded-full bg-red-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-red-600 transition-colors"
        >
          <PhoneOff size={16} />
          Beenden
        </button>
      )}

      <button
        onClick={onLeave}
        className="flex items-center gap-2 rounded-full bg-gray-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-600 transition-colors"
      >
        <PhoneOff size={16} />
        Verlassen
      </button>
    </div>
  );
}
