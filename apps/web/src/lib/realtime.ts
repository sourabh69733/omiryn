/** Maintains the browser's authenticated realtime connection and room subscription. */

import { apiFetch, apiWebSocketUrl } from "./api";

export type RealtimeEvent = {
  event_id?: string;
  type: string;
  scope?: "user" | "conversation";
  scope_id?: string;
  sequence?: number | null;
  occurred_at?: string;
  version: number;
  payload: Record<string, unknown>;
};

type RealtimeTicket = { ticket: string };
type RealtimeEventHandler = (event: RealtimeEvent) => void;

const HEARTBEAT_INTERVAL_MS = 25_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private conversationId: string | null = null;
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private stopped = true;

  constructor(private readonly onEvent: RealtimeEventHandler) {}

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop() {
    this.stopped = true;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, "Client stopped");
  }

  setConversation(conversationId: string | null) {
    if (this.conversationId === conversationId) return;
    const previousId = this.conversationId;
    this.conversationId = conversationId;
    if (!this.isOpen()) return;
    if (previousId) this.sendRoomCommand("unsubscribe", previousId);
    if (conversationId) this.sendRoomCommand("subscribe", conversationId);
  }

  private async connect() {
    if (this.stopped || this.socket) return;
    try {
      const response = await apiFetch("/api/realtime/ticket", { method: "POST" });
      if (!response.ok) throw new Error("Could not authorize realtime connection.");
      const { ticket } = (await response.json()) as RealtimeTicket;
      if (this.stopped) return;

      const url = apiWebSocketUrl("/api/realtime");
      url.searchParams.set("ticket", ticket);
      const socket = new WebSocket(url);
      this.socket = socket;

      socket.onopen = () => {
        if (this.socket !== socket) return;
        this.reconnectAttempt = 0;
        if (this.conversationId) this.sendRoomCommand("subscribe", this.conversationId);
        this.startHeartbeat();
      };
      socket.onmessage = (message) => {
        const event = parseRealtimeEvent(message.data);
        if (event) this.onEvent(event);
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (this.socket === socket) this.socket = null;
        this.stopHeartbeat();
        this.scheduleReconnect();
      };
    } catch {
      this.socket = null;
      this.scheduleReconnect();
    }
  }

  private sendRoomCommand(type: "subscribe" | "unsubscribe", conversationId: string) {
    this.send({ type, scope: "conversation", scope_id: conversationId });
  }

  private send(payload: Record<string, unknown>) {
    if (this.isOpen()) this.socket?.send(JSON.stringify(payload));
  }

  private isOpen() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => this.send({ type: "ping" }), HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer !== null) window.clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer !== null) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, MAX_RECONNECT_DELAY_MS);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  private clearTimers() {
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.stopHeartbeat();
  }
}

function parseRealtimeEvent(raw: unknown): RealtimeEvent | null {
  if (typeof raw !== "string") return null;
  try {
    const candidate = JSON.parse(raw) as Partial<RealtimeEvent>;
    if (!candidate || typeof candidate !== "object") return null;
    if (typeof candidate.type !== "string" || candidate.version !== 1) return null;
    if (!candidate.payload || typeof candidate.payload !== "object" || Array.isArray(candidate.payload)) return null;
    return candidate as RealtimeEvent;
  } catch {
    return null;
  }
}
