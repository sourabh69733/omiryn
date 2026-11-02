import type { Message } from "./types";

// The chat holds what the server saved, then the bubbles still on their way (`local`). Several can
// be on their way at once: Omi may be replying while the user keeps writing. Whatever arrives from
// the server replaces only the saved part, so a bubble never vanishes and never shows twice.

export function newClientId() {
  return crypto.randomUUID();
}

function saved(messages: Message[]) {
  return messages.filter((message) => !message.local);
}

function stillOnTheirWay(messages: Message[], arrived: Message[]) {
  const ids = new Set(arrived.map((message) => message.client_id).filter(Boolean));
  return messages.filter((message) => message.local && !ids.has(message.client_id));
}

// A response from the server. One written before newer events (a shorter list) changes nothing
// except that its bubbles have landed.
export function mergeServerMessages(current: Message[], server: Message[]): Message[] {
  const known = saved(current);
  const base = server.length >= known.length ? server : known;
  return [...base, ...stillOnTheirWay(current, [...server, ...known])];
}

// One saved message from a realtime event or recovery. A reply saved above a later message moves
// that message down, so a different message at this index replaces what is there.
export function applyMessageAt(current: Message[], index: number, message: Message): Message[] {
  const known = saved(current);
  if (index > known.length) return current;
  const next = [...known];
  const existing = next[index];
  const same = existing && existing.role === message.role && existing.content === message.content;
  next[index] = same ? { ...existing, ...message } : message;
  return [...next, ...stillOnTheirWay(current, [message])];
}

export function dropLocal(messages: Message[], clientId: string): Message[] {
  return messages.filter((message) => !(message.local && message.client_id === clientId));
}

// No answer at all: the server may never have seen this one.
export function markLocalFailed(messages: Message[], clientId: string): Message[] {
  return messages.map((message) => (message.local && message.client_id === clientId ? { ...message, delivery_status: "failed" } : message));
}

// The reply failed: the server marked every unanswered message, and this request's own is saved.
export function markBurstFailed(messages: Message[], clientId: string | null): Message[] {
  return messages.map((message) => {
    if (message.local && message.client_id === clientId) return { ...message, local: false, delivery_status: "failed" };
    if (!message.local && message.role === "user" && message.delivery_status === "sending") return { ...message, delivery_status: "failed" };
    return message;
  });
}

// Only the newest failed message offers Retry; retrying answers them all.
export function lastFailedIndex(messages: Message[], isFailed: (message: Message) => boolean) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (isFailed(messages[index])) return index;
  }
  return -1;
}
