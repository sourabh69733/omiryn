import type { Message } from "./types";

const BASE_DELAY_MS = 600;
const PER_CHARACTER_MS = 30;
const MAX_DELAY_MS = 2600;

/**
 * How long to wait before showing messages[index], in milliseconds.
 *
 * Bubbles from one agent reply share a created_at; the second and later ones appear after a
 * typing pause sized to their length, like a person sending several texts. Everything else
 * (user messages, the first bubble of a reply, older history) shows immediately.
 */
export function nextBubbleDelay(messages: Message[], index: number): number {
  const next = messages[index];
  const previous = messages[index - 1];
  if (!next || !previous) return 0;
  if (next.role !== "assistant" || previous.role !== "assistant") return 0;
  if (!next.created_at || next.created_at !== previous.created_at) return 0;
  return Math.min(MAX_DELAY_MS, BASE_DELAY_MS + Array.from(next.content || "").length * PER_CHARACTER_MS);
}
