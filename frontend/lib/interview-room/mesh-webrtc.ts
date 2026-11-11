"use client";

/**
 * MeshManager – N:N WebRTC mesh for interview rooms.
 *
 * Uses "perfect negotiation" to avoid offer collisions:
 * - polite = myUserId < remoteUserId (lexicographic)
 * - polite peer defers on collision (ignores offer, rolls back local description)
 */

export const RTC_CONFIG: RTCConfiguration = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
  ],
};

type SendSignal = (msg: Record<string, unknown>) => void;
type StreamCallback = (peerId: string, stream: MediaStream) => void;
type PeerLeftCallback = (peerId: string) => void;

interface PeerState {
  pc: RTCPeerConnection;
  makingOffer: boolean;
  ignoreOffer: boolean;
}

export class MeshManager {
  private peers: Map<string, PeerState> = new Map();
  private localStream: MediaStream | null = null;

  constructor(
    private readonly myUserId: string,
    private readonly roomId: string,
    private readonly sendSignal: SendSignal,
    private readonly onRemoteStream: StreamCallback,
    private readonly onPeerLeft: PeerLeftCallback,
  ) {}

  setLocalStream(stream: MediaStream): void {
    this.localStream = stream;
    // Add tracks to all existing connections
    for (const [, state] of this.peers) {
      stream.getTracks().forEach((track) => {
        state.pc.addTrack(track, stream);
      });
    }
  }

  /** Called when a new peer joins the room. We initiate the offer. */
  async addPeer(peerId: string): Promise<void> {
    if (this.peers.has(peerId) || peerId === this.myUserId) return;

    const state = this._createPeerState(peerId);
    this.peers.set(peerId, state);

    // Add local tracks if available
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => {
        state.pc.addTrack(track, this.localStream!);
      });
    }

    // Initiate offer
    try {
      state.makingOffer = true;
      await state.pc.setLocalDescription();
      this.sendSignal({
        type: "interview.webrtc_offer",
        room_id: this.roomId,
        target_peer_id: peerId,
        from_peer_id: this.myUserId,
        sdp: state.pc.localDescription,
      });
    } catch (err) {
      console.error("addPeer offer error", err);
    } finally {
      state.makingOffer = false;
    }
  }

  removePeer(peerId: string): void {
    const state = this.peers.get(peerId);
    if (state) {
      state.pc.close();
      this.peers.delete(peerId);
      this.onPeerLeft(peerId);
    }
  }

  /** Handle incoming WS signals for WebRTC */
  async handleSignal(msg: Record<string, unknown>): Promise<void> {
    const type = msg.type as string;
    const fromPeerId = (msg.from_peer_id as string) ?? "";
    if (!fromPeerId || fromPeerId === this.myUserId) return;

    if (type === "interview.webrtc_offer") {
      await this._handleOffer(fromPeerId, msg.sdp as RTCSessionDescriptionInit);
    } else if (type === "interview.webrtc_answer") {
      await this._handleAnswer(fromPeerId, msg.sdp as RTCSessionDescriptionInit);
    } else if (type === "interview.webrtc_ice") {
      await this._handleIce(fromPeerId, msg.candidate as RTCIceCandidateInit);
    }
  }

  destroy(): void {
    for (const [, state] of this.peers) {
      state.pc.close();
    }
    this.peers.clear();
    this.localStream?.getTracks().forEach((t) => t.stop());
    this.localStream = null;
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private _createPeerState(peerId: string): PeerState {
    const pc = new RTCPeerConnection(RTC_CONFIG);
    const state: PeerState = { pc, makingOffer: false, ignoreOffer: false };

    pc.onicecandidate = ({ candidate }) => {
      if (candidate) {
        this.sendSignal({
          type: "interview.webrtc_ice",
          room_id: this.roomId,
          target_peer_id: peerId,
          from_peer_id: this.myUserId,
          candidate,
        });
      }
    };

    pc.ontrack = (event) => {
      if (event.streams[0]) {
        this.onRemoteStream(peerId, event.streams[0]);
      }
    };

    pc.onnegotiationneeded = async () => {
      try {
        state.makingOffer = true;
        await pc.setLocalDescription();
        this.sendSignal({
          type: "interview.webrtc_offer",
          room_id: this.roomId,
          target_peer_id: peerId,
          from_peer_id: this.myUserId,
          sdp: pc.localDescription,
        });
      } catch (err) {
        console.error("negotiationneeded error", err);
      } finally {
        state.makingOffer = false;
      }
    };

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed" || pc.connectionState === "closed") {
        this.removePeer(peerId);
      }
    };

    return state;
  }

  private _isPolite(peerId: string): boolean {
    // Polite peer = the one with the lexicographically smaller userId
    return this.myUserId < peerId;
  }

  private async _handleOffer(fromPeerId: string, sdp: RTCSessionDescriptionInit): Promise<void> {
    let state = this.peers.get(fromPeerId);
    if (!state) {
      state = this._createPeerState(fromPeerId);
      this.peers.set(fromPeerId, state);
      if (this.localStream) {
        this.localStream.getTracks().forEach((track) => {
          state!.pc.addTrack(track, this.localStream!);
        });
      }
    }

    const { pc } = state;
    const offerCollision =
      sdp.type === "offer" &&
      (state.makingOffer || pc.signalingState !== "stable");

    state.ignoreOffer = !this._isPolite(fromPeerId) && offerCollision;
    if (state.ignoreOffer) return;

    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    if (sdp.type === "offer") {
      await pc.setLocalDescription();
      this.sendSignal({
        type: "interview.webrtc_answer",
        room_id: this.roomId,
        target_peer_id: fromPeerId,
        from_peer_id: this.myUserId,
        sdp: pc.localDescription,
      });
    }
  }

  private async _handleAnswer(fromPeerId: string, sdp: RTCSessionDescriptionInit): Promise<void> {
    const state = this.peers.get(fromPeerId);
    if (!state || state.ignoreOffer) return;
    try {
      await state.pc.setRemoteDescription(new RTCSessionDescription(sdp));
    } catch {
      // ignore stale answer
    }
  }

  private async _handleIce(fromPeerId: string, candidate: RTCIceCandidateInit): Promise<void> {
    const state = this.peers.get(fromPeerId);
    if (!state) return;
    try {
      await state.pc.addIceCandidate(new RTCIceCandidate(candidate));
    } catch (error) {
      if (!state.ignoreOffer) throw error;
    }
  }
}
