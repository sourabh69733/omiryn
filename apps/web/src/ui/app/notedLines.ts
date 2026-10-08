import type { Message } from "./types";
import type { VibeArea } from "./vibe";

export type NotedLine = { areaId: string; text: string; private: boolean };

// Where each vibe line shows in the chat as "Noted: ...": once, at its newest proof, right after
// Omi's reply to that message (or under the message itself while the reply is still coming).
// Lines whose newest proof is in another chat show there, not here.
export function notedLinesByMessage(areas: VibeArea[], conversationId: string, messages: Message[]): Map<number, NotedLine[]> {
  const placed = new Map<number, NotedLine[]>();
  for (const area of areas) {
    const newest = area.evidence[0];
    if (!area.text || !newest || newest.conversation_id !== conversationId) continue;
    const userIndex = newest.message_index;
    if (userIndex < 0 || userIndex >= messages.length) continue;
    let at = userIndex;
    while (at + 1 < messages.length && messages[at + 1].role === "assistant") at += 1;
    const lines = placed.get(at) || [];
    lines.push({ areaId: area.id, text: area.text, private: area.private });
    placed.set(at, lines);
  }
  return placed;
}
