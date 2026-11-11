"use client";

import { ParticipantTile } from "./ParticipantTile";

export interface RemotePeer {
  peerId: string;
  displayName: string;
  stream: MediaStream | null;
  audioMuted: boolean;
  videoMuted: boolean;
}

interface Props {
  localStream: MediaStream | null;
  localName: string;
  localAudioMuted: boolean;
  localVideoMuted: boolean;
  remotePeers: RemotePeer[];
}

export function VideoGrid({ localStream, localName, localAudioMuted, localVideoMuted, remotePeers }: Props) {
  const total = remotePeers.length + 1; // +1 for self

  // Choose grid layout based on participant count
  const gridClass =
    total === 1 ? "grid-cols-1" :
    total === 2 ? "grid-cols-2" :
    total <= 4 ? "grid-cols-2" :
    total <= 6 ? "grid-cols-3" :
    "grid-cols-3";

  return (
    <div className={`grid ${gridClass} gap-2 p-2 h-full auto-rows-fr`}>
      {/* Self */}
      <ParticipantTile
        peerId="local"
        displayName={localName}
        stream={localStream}
        isLocal
        audioMuted={localAudioMuted}
        videoMuted={localVideoMuted}
      />
      {/* Remote peers */}
      {remotePeers.map((peer) => (
        <ParticipantTile
          key={peer.peerId}
          peerId={peer.peerId}
          displayName={peer.displayName}
          stream={peer.stream}
          audioMuted={peer.audioMuted}
          videoMuted={peer.videoMuted}
        />
      ))}
    </div>
  );
}
