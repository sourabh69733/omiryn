import type { ConversationSummary } from "./types";

// How many messages the user has seen in each chat, kept in this browser only.
export type SeenCounts = Readonly<Record<string, number>>;

const STORAGE_KEY = "omiryn.seenMessageCounts";

export function loadSeen(): SeenCounts {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

export function saveSeen(seen: SeenCounts): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seen));
  } catch {
    // Private mode or blocked storage: unread dots just reset on reload.
  }
}

// A chat this browser has never listed counts as read, so old chats do not all light up at once.
export function withNewChatsSeen(seen: SeenCounts, summaries: ConversationSummary[]): SeenCounts {
  const missing = summaries.filter((item) => seen[item.id] === undefined);
  if (!missing.length) return seen;
  return { ...seen, ...Object.fromEntries(missing.map((item) => [item.id, item.message_count || 0])) };
}

export function markSeen(seen: SeenCounts, id: string, count: number): SeenCounts {
  return seen[id] === count ? seen : { ...seen, [id]: count };
}

// The open chat is never unread; the user is looking at it.
export function isUnread(summary: ConversationSummary, seen: SeenCounts, openId: string | null): boolean {
  if (summary.id === openId) return false;
  const count = seen[summary.id];
  return count !== undefined && (summary.message_count || 0) > count;
}
