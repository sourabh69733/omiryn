import type { RealtimeEvent } from "../../lib/realtime";

// The companion's own messages (greetings, follow-ups, story parts) announce typing over realtime.
// Returns the conversation that is now typing, or null; `current` is kept for unrelated events.
export function typingAfterEvent(event: RealtimeEvent, current: string | null): string | null {
  if (event.scope !== "conversation" || !event.scope_id) return current;
  if (event.type === "agent.typing") {
    if (event.payload.active === true) return event.scope_id;
    return current === event.scope_id ? null : current;
  }
  const message = event.payload.message as { role?: unknown } | undefined;
  if (event.type === "message.created" && message?.role === "assistant" && current === event.scope_id) {
    return null; // the message arrived; the bubble reveal takes over
  }
  return current;
}

// Never leave dots up if the "done" event is lost.
export const AGENT_TYPING_TIMEOUT_MS = 90000;
