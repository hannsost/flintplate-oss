/**
 * WebSocket client with auto-reconnect and typed events.
 * Sprint 1.1 – Real-Time Kanban + Notifications
 */

export type WsEventType =
  | "application.created"
  | "application.updated"
  | "application.deleted"
  | "notification.new"
  | "support.incoming"
  | "support.accepted"
  | "support.rejected"
  | "support.ended"
  | "support.consent_granted"
  | "support.agent_ready"
  | "support.webrtc_offer"
  | "support.webrtc_answer"
  | "support.webrtc_ice"
  | "support.dom_snapshot"
  | "support.dom_events"
  | "support.control_mouse"
  | "support.control_keyboard"
  | "support.cursor_move"
  | "support.session_join"
  | "interview.room_join"
  | "interview.room_leave"
  | "interview.peer_joined"
  | "interview.peer_left"
  | "interview.webrtc_offer"
  | "interview.webrtc_answer"
  | "interview.webrtc_ice"
  | "interview.chat_message"
  | "interview.media_state"
  | "interview.room_ended"

export interface WsEvent {
  type: WsEventType
  payload: Record<string, unknown>
}

type EventHandler = (event: WsEvent) => void

class PalmscoutWebSocket {
  private ws: WebSocket | null = null
  private handlers: Map<WsEventType | "*", Set<EventHandler>> = new Map()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 2000
  private maxDelay = 30_000
  private stopped = false
  private pingInterval: ReturnType<typeof setInterval> | null = null
  private _pendingOnOpen: Array<() => void> = []

  connect(token: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.stopped = false
    this._open(token)
  }

  disconnect(): void {
    this.stopped = true
    this._clearTimers()
    this._pendingOnOpen = []
    this.ws?.close()
    this.ws = null
  }

  on(type: WsEventType | "*", handler: EventHandler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set())
    this.handlers.get(type)!.add(handler)
    return () => this.handlers.get(type)?.delete(handler)
  }

  /** Subscribe to all incoming messages with a loosely typed handler.
   *  Support events arrive flat (no payload wrapper), so use this for them. */
  onAny(handler: (msg: Record<string, unknown>) => void): () => void {
    const wrapped: EventHandler = (e) => handler(e as unknown as Record<string, unknown>)
    return this.on("*", wrapped)
  }

  /** Send a raw JSON-serialisable message over the WebSocket. */
  send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  /** Run callback as soon as the socket is open; if already open, runs immediately. */
  whenConnected(fn: () => void): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      fn()
    } else {
      this._pendingOnOpen.push(fn)
    }
  }

  private _open(token: string): void {
    const proto = window.location.protocol === "https:" ? "wss" : "ws"
    const host = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") ?? "localhost:8000"
    const url = `${proto}://${host}/ws?token=${encodeURIComponent(token)}`

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.reconnectDelay = 2000
      this._clearTimers()
      // keepalive ping every 20 s
      this.pingInterval = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send("ping")
      }, 20_000)
      // Flush any callbacks that were queued before the socket opened
      const pending = this._pendingOnOpen.splice(0)
      pending.forEach((fn) => fn())
    }

    this.ws.onmessage = (e) => {
      if (e.data === "pong") return
      try {
        const event: WsEvent = JSON.parse(e.data)
        this._dispatch(event)
      } catch {
        // ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this._clearTimers()
      if (!this.stopped) this._scheduleReconnect(token)
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private _dispatch(event: WsEvent): void {
    this.handlers.get(event.type)?.forEach((h) => h(event))
    this.handlers.get("*")?.forEach((h) => h(event))
  }

  private _scheduleReconnect(token: string): void {
    this.reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxDelay)
      this._open(token)
    }, this.reconnectDelay)
  }

  private _clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.pingInterval) clearInterval(this.pingInterval)
    this.reconnectTimer = null
    this.pingInterval = null
  }
}

// Singleton – one connection per browser tab
export const wsClient = new PalmscoutWebSocket()
