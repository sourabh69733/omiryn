import { VIBE_AREA_LABELS } from "./vibe";
import type { Message } from "./types";

export type MessageDeletionImpact = {
  message_count: number;
  memories_forgotten: number;
  vibe_removed: string[];
  vibe_weakened: string[];
};

export function toggleSelected(selected: number[], index: number): number[] {
  return selected.includes(index) ? selected.filter((item) => item !== index) : [...selected, index].sort((a, b) => a - b);
}

// Deleted messages stay as empty placeholders so links by position keep working; never shown.
export function isDeletedMessage(message: Pick<Message, "deleted">): boolean {
  return Boolean(message.deleted);
}

export function messageDeletionImpactLines(impact: MessageDeletionImpact): string[] {
  const names = (ids: string[]) => ids.map((id) => VIBE_AREA_LABELS[id] || id).join(", ");
  const lines: string[] = [];
  const count = impact.memories_forgotten;
  if (count === 1) lines.push("Omi will forget 1 thing it learned only from these messages.");
  else if (count > 1) lines.push(`Omi will forget ${count} things it learned only from these messages.`);
  if (impact.vibe_removed.length) lines.push(`Removed from your vibe: ${names(impact.vibe_removed)}.`);
  if (impact.vibe_weakened.length) lines.push(`Less proof for: ${names(impact.vibe_weakened)}.`);
  lines.push("Omi rebuilds this chat's summary from what's left.");
  return lines;
}

export function markDeleted(messages: Message[], indexes: number[]): Message[] {
  const chosen = new Set(indexes);
  return messages.map((message, index) =>
    chosen.has(index) ? { role: message.role, content: "", deleted: true, created_at: message.created_at } : message,
  );
}
