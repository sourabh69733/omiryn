import type { RealtimeEvent } from "../../lib/realtime";

export type VibeArea = {
  id: string;
  stage: "basics" | "deeper";
  // Used for matching only; never shown to matches.
  private: boolean;
  text: string | null;
  // clear: said on 2+ different days; mentioned: one day only. Milestones past the first need clear.
  strength: "clear" | "mentioned" | null;
  evidence_count: number;
  evidence_days: number;
  // The user's own messages behind the line, newest first.
  evidence: VibeEvidence[];
};
export type VibeEvidence = { quote: string; conversation_id: string; message_index: number; sent_at: string | null };
export type Vibe = {
  milestone: string;
  next_milestone: string | null;
  milestone_reached_at: string | null;
  known: number;
  total: number;
  areas: VibeArea[];
};

export const VIBE_AREA_LABELS: Record<string, string> = {
  friend_wish: "What you want in a friend",
  humor: "Your humor",
  social_energy: "Your social energy",
  interests: "What you love",
  daily_life: "Your days",
  values: "What you believe in",
  stories: "Stories that shaped you",
  accepts: "Differences you're fine with",
  deal_breakers: "Deal-breakers",
  conflict: "How you handle conflict",
  keeping_in_touch: "Keeping in touch",
};

// The path shown to the user; "starting" is before the first step.
export const VIBE_STEPS = [
  { id: "first_impressions", label: "First impressions", note: "Omi has a first sense of your vibe." },
  { id: "basics", label: "The basics", note: "Omi knows what you want in friends." },
  { id: "ready_to_match", label: "Ready to match", note: "Omi knows you well enough to look for friends." },
  { id: "deep", label: "Deep", note: "Omi really gets your vibe." },
] as const;

export function vibeStepIndex(milestone: string): number {
  return VIBE_STEPS.findIndex((step) => step.id === milestone);
}

export function vibeStepNote(milestone: string): string | null {
  return VIBE_STEPS.find((step) => step.id === milestone)?.note ?? null;
}

// A milestone the background reached while this chat is open; only moves forward are news.
export function milestoneFromEvent(event: RealtimeEvent, conversationId: string | null): string | null {
  if (event.type !== "vibe.milestone" || event.scope !== "conversation" || event.scope_id !== conversationId) return null;
  const milestone = typeof event.payload.milestone === "string" ? event.payload.milestone : "";
  const previous = typeof event.payload.previous === "string" ? event.payload.previous : "starting";
  return vibeStepIndex(milestone) > vibeStepIndex(previous) ? milestone : null;
}

export type DeletionImpact = {
  memories_forgotten: number;
  vibe_removed: string[];
  vibe_weakened: string[];
  topics_dropped?: string[];
};

// Plain lines for the delete dialog: what goes with the chat.
export function deletionImpactLines(impact: DeletionImpact): string[] {
  const names = (ids: string[]) => ids.map((id) => VIBE_AREA_LABELS[id] || id).join(", ");
  const lines: string[] = [];
  if (impact.memories_forgotten === 1) lines.push("Omi will forget 1 thing it learned only from this chat.");
  else if (impact.memories_forgotten > 1) lines.push(`Omi will forget ${impact.memories_forgotten} things it learned only from this chat.`);
  const removed = impact.vibe_removed ?? [];
  const weakened = impact.vibe_weakened ?? [];
  if (removed.length) lines.push(`Removed from your vibe: ${names(removed)}.`);
  if (weakened.length) lines.push(`Less proof for: ${names(weakened)}.`);
  const topics = impact.topics_dropped ?? [];
  if (topics.length) lines.push(`Omi won't bring these up again: ${topics.join(", ")}.`);
  return lines;
}

// Opens the chat at that message; ChatPage scrolls to #message-N and highlights it.
export function evidenceChatPath(item: Pick<VibeEvidence, "conversation_id" | "message_index">): string {
  return `/?conversation_id=${encodeURIComponent(item.conversation_id)}#message-${item.message_index}`;
}

// The chip says one thing: Confirmed when said on different days (counts toward matches), else
// Still learning. Its color deepens with the proof (see confidenceLevel).
export function strengthLabel(strength: VibeArea["strength"]): string {
  return strength === "clear" ? "Confirmed" : "Still learning";
}

// 1: one message. 2: several messages, one day. 3: two days. 4: three or more days.
export function confidenceLevel(count: number, days: number): 1 | 2 | 3 | 4 {
  if (days >= 3) return 4;
  if (days >= 2) return 3;
  return count >= 2 ? 2 : 1;
}

// The count lives in the proof panel, under the chip.
export function proofSummary(count: number, days: number): string {
  const messages = count === 1 ? "1 of your messages" : `${count} of your messages`;
  return days >= 2 ? `From ${messages}, on ${days} different days` : `From ${messages}`;
}
