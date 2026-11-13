// People: the chats with people Omi introduced, shown beside the chat with Omi. The logic the
// rail rows and the person chat screen need; the server (docs/api-contract.md, "Card field chat")
// decides who may read and write.
import type { MatchCard } from "./matches";

export type PersonMessage = { id: number; mine: boolean; text: string; created_at: string; client_id?: string | null; pending?: boolean; failed?: boolean };

/** A realtime event about a match, passed on by the chat page's socket. */
export const MATCH_EVENT = "omi:match-event";
export type MatchEventDetail = { type: string; payload: { pair_id?: string; message_id?: number } };

/** People to show in the chat list, newest activity first. An open chat always shows (one nobody
    wrote in yet sorts by its introduction); a closed one only while it holds messages to read; a
    person the user blocked never does. */
export function peopleRows(cards: MatchCard[]): MatchCard[] {
  const at = (card: MatchCard) => card.chat?.last_at || card.introduced_at || card.asked_at || "";
  return cards
    .filter((card) => card.chat && card.status !== "blocked" && (card.chat.open || card.chat.messages > 0))
    .sort((a, b) => at(b).localeCompare(at(a)));
}

/** The line under a person's name in the chat list. */
export function previewLine(card: MatchCard): string {
  const chat = card.chat;
  if (!chat) return "";
  if (chat.last_text) return chat.last_mine ? `You: ${chat.last_text}` : chat.last_text;
  return chat.open ? "You both said hi. Say something." : "Chat closed";
}

/** The unread badge: nothing at zero, capped so the row never grows. */
export function unreadLabel(count: number | undefined | null): string {
  if (!count || count < 1) return "";
  return count > 9 ? "9+" : String(count);
}

export function totalUnread(cards: MatchCard[]): number {
  return cards.reduce((sum, card) => sum + (card.chat?.unread ?? 0), 0);
}

/** Add fetched messages to what is on screen: one row per id, a confirmed send replaces its pending
    bubble (matched by client id), oldest first with pending bubbles last. */
export function mergeMessages(current: PersonMessage[], incoming: PersonMessage[]): PersonMessage[] {
  const confirmed = new Set(incoming.map((message) => message.client_id).filter(Boolean));
  const byId = new Map<number, PersonMessage>();
  for (const message of current) {
    if (message.pending && message.client_id && confirmed.has(message.client_id)) continue;
    byId.set(message.id, message);
  }
  for (const message of incoming) byId.set(message.id, message);
  const rows = [...byId.values()];
  return [...rows.filter((m) => !m.pending).sort((a, b) => a.id - b.id), ...rows.filter((m) => m.pending)];
}

export function newestId(messages: PersonMessage[]): number {
  return messages.reduce((max, message) => (message.pending ? max : Math.max(max, message.id)), 0);
}

const dayKey = (iso: string) => new Date(iso).toDateString();

/** A date line goes above the first message of each day. */
export function startsDay(messages: PersonMessage[], index: number): boolean {
  return index === 0 || dayKey(messages[index - 1].created_at) !== dayKey(messages[index].created_at);
}

/** Bubbles from one person within a few minutes read as one cluster, as in the chat with Omi. */
export function clusterClass(messages: PersonMessage[], index: number): string {
  const near = (a: PersonMessage | undefined, b: PersonMessage | undefined) =>
    Boolean(a && b && a.mine === b.mine && dayKey(a.created_at) === dayKey(b.created_at) && Math.abs(new Date(b.created_at).getTime() - new Date(a.created_at).getTime()) < 20 * 60_000);
  const before = near(messages[index - 1], messages[index]);
  const after = near(messages[index], messages[index + 1]);
  return !before && !after ? "cluster-single" : !before ? "cluster-start" : !after ? "cluster-end same-cluster" : "cluster-middle same-cluster";
}

export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const days = Math.round((new Date(now.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: date.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

export const personPath = (pairId: string) => `/people/${encodeURIComponent(pairId)}`;

/** The pair id in a /people/<id> address, or null. */
export function pairFromPath(pathname: string): string | null {
  const found = /^\/people\/([^/]+)/.exec(pathname);
  return found ? decodeURIComponent(found[1]) : null;
}
