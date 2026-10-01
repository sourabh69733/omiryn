import type { RealtimeEvent } from "../../lib/realtime";

export type VibeArea = {
  id: string;
  stage: "basics" | "deeper";
  text: string | null;
  // clear: seen in 2+ of the user's messages; mentioned: once. Milestones past the first need clear.
  strength: "clear" | "mentioned" | null;
  evidence_count: number;
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

// Opens the chat at that message; ChatPage scrolls to #message-N and highlights it.
export function evidenceChatPath(item: Pick<VibeEvidence, "conversation_id" | "message_index">): string {
  return `/?conversation_id=${encodeURIComponent(item.conversation_id)}#message-${item.message_index}`;
}
