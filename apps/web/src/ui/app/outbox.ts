import type { Message } from "./types";

// What the user wrote must survive a server that is down and a page refresh. Two things are kept
// in this browser until the server has them: the draft in the box, and each sent message the
// server has not confirmed. Both are per chat, never for a Temporary Chat, and cleared on sign out.
// Storage can be missing or full (private mode); then the chat still works, it just keeps nothing.

export type OutboxItem = { client_id: string; content: string; created_at: string };

const OUTBOX = "omiryn.outbox.";
const DRAFT = "omiryn.draft.";

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = store()?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown | null) {
  try {
    if (value === null) store()?.removeItem(key);
    else store()?.setItem(key, JSON.stringify(value));
  } catch {
    // Full or blocked storage: nothing is kept, the chat goes on.
  }
}

export function loadOutbox(conversationId: string): OutboxItem[] {
  const items = read<unknown>(OUTBOX + conversationId, []);
  return Array.isArray(items) ? items.filter((item): item is OutboxItem => Boolean(item?.client_id && typeof item.content === "string")) : [];
}

function saveOutbox(conversationId: string, items: OutboxItem[]) {
  write(OUTBOX + conversationId, items.length ? items : null);
}

export function addToOutbox(conversationId: string, item: OutboxItem) {
  saveOutbox(conversationId, [...loadOutbox(conversationId).filter((saved) => saved.client_id !== item.client_id), item]);
}

export function removeFromOutbox(conversationId: string, clientId: string) {
  saveOutbox(conversationId, loadOutbox(conversationId).filter((item) => item.client_id !== clientId));
}

// After a chat loads: what the server already has leaves the outbox, and the rest comes back as
// "Not sent" bubbles with Retry, in the order they were written. The server ignores a client id
// it has seen, so a retry never sends one twice.
export function restoreOutbox(conversationId: string, messages: Message[]): Message[] {
  const onServer = new Set(messages.map((message) => message.client_id).filter(Boolean));
  const left = loadOutbox(conversationId).filter((item) => !onServer.has(item.client_id));
  saveOutbox(conversationId, left);
  const shown = new Set(messages.filter((message) => message.local).map((message) => message.client_id));
  const missing = left.filter((item) => !shown.has(item.client_id));
  return missing.length
    ? [...messages, ...missing.map((item): Message => ({ role: "user", content: item.content, created_at: item.created_at, client_id: item.client_id, local: true, delivery_status: "failed" }))]
    : messages;
}

export function loadDraft(conversationId: string): string {
  const draft = read<unknown>(DRAFT + conversationId, "");
  return typeof draft === "string" ? draft : "";
}

export function saveDraft(conversationId: string, draft: string) {
  write(DRAFT + conversationId, draft.trim() ? draft : null);
}

// On sign out nothing written stays behind for the next person on this browser.
export function clearSavedWriting() {
  const storage = store();
  if (!storage) return;
  try {
    const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index)).filter((key): key is string => Boolean(key));
    for (const key of keys) if (key.startsWith(OUTBOX) || key.startsWith(DRAFT)) storage.removeItem(key);
  } catch {
    // Nothing to clear.
  }
}
