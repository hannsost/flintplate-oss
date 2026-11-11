"use client";

/**
 * WebRTC peer connection helpers for support sessions.
 * Uses the existing WS connection for signaling.
 */

export const RTC_CONFIG: RTCConfiguration = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
};

export type SignalSender = (msg: Record<string, unknown>) => void;

export async function createPeerConnection(
  sessionId: string,
  sendSignal: SignalSender,
  onRemoteStream: (stream: MediaStream) => void,
  onIceCandidate?: (candidate: RTCIceCandidate) => void,
): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection(RTC_CONFIG);

  pc.onicecandidate = ({ candidate }) => {
    if (candidate) {
      sendSignal({ type: "support.webrtc_ice", session_id: sessionId, candidate });
    }
  };

  pc.ontrack = (event) => {
    if (event.streams[0]) onRemoteStream(event.streams[0]);
  };

  return pc;
}

export async function createOffer(
  pc: RTCPeerConnection,
  sessionId: string,
  sendSignal: SignalSender,
): Promise<void> {
  const offer = await pc.createOffer({ offerToReceiveAudio: true, offerToReceiveVideo: true });
  await pc.setLocalDescription(offer);
  sendSignal({ type: "support.webrtc_offer", session_id: sessionId, sdp: offer });
}

export async function handleOffer(
  pc: RTCPeerConnection,
  sessionId: string,
  sdp: RTCSessionDescriptionInit,
  sendSignal: SignalSender,
): Promise<void> {
  await pc.setRemoteDescription(new RTCSessionDescription(sdp));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  sendSignal({ type: "support.webrtc_answer", session_id: sessionId, sdp: answer });
}

export async function handleAnswer(
  pc: RTCPeerConnection,
  sdp: RTCSessionDescriptionInit,
): Promise<void> {
  await pc.setRemoteDescription(new RTCSessionDescription(sdp));
}

export async function addIceCandidate(
  pc: RTCPeerConnection,
  candidate: RTCIceCandidateInit,
): Promise<void> {
  try {
    await pc.addIceCandidate(new RTCIceCandidate(candidate));
  } catch {
    // ignore stale candidates
  }
}

/** Get user media (mic + optional camera) */
export async function getUserMedia(video: boolean, audio: boolean): Promise<MediaStream | null> {
  if (!video && !audio) return null;
  try {
    return await navigator.mediaDevices.getUserMedia({ video, audio });
  } catch {
    return null;
  }
}
