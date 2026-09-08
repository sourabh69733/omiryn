import type { CanonicalMemory } from "./types";

export type CanonicalMemorySection = {
  id: CanonicalMemory["kind"];
  title: string;
  summary: string;
  memories: CanonicalMemory[];
};

const sectionDefinitions: Array<Omit<CanonicalMemorySection, "memories">> = [
  { id: "semantic", title: "Facts about you", summary: "Stable knowledge such as your background, preferences, and situation." },
  { id: "episodic", title: "Experiences", summary: "Events and stories that happened at a particular time." },
  { id: "relationship", title: "Relationships", summary: "Your lived history and evolving dynamics with particular people." },
  { id: "procedural", title: "Conversation preferences", summary: "How Omiryn should communicate and work with you." }
];

export function groupCanonicalMemories(memories: CanonicalMemory[]): CanonicalMemorySection[] {
  return sectionDefinitions
    .map((section) => ({
      ...section,
      memories: memories.filter((memory) => memory.kind === section.id)
    }))
    .filter((section) => section.memories.length > 0);
}

export function canonicalMemoryValueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(canonicalMemoryValueText).filter(Boolean).join(" · ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replaceAll("_", " ")}: ${canonicalMemoryValueText(item)}`)
      .filter((item) => !item.endsWith(": "))
      .join(" · ");
  }
  return String(value).trim();
}


export function canonicalMemoryControls(evidenceCount: number): Array<{ id: "evidence" | "review" | "usage"; label: string }> {
  const controls: Array<{ id: "evidence" | "review" | "usage"; label: string }> = [];
  if (evidenceCount > 0) controls.push({ id: "evidence", label: String(evidenceCount) + " evidence" });
  controls.push(
    { id: "review", label: "Review accuracy" },
    { id: "usage", label: "Usage" }
  );
  return controls;
}

export function canonicalMemoryEvidenceHref(
  evidence: { conversation_id?: string; message_index?: number | null },
  origin: string
): string {
  if (!evidence.conversation_id) return "";
  const url = new URL("/", origin);
  url.searchParams.set("conversation_id", evidence.conversation_id);
  if (typeof evidence.message_index === "number") {
    url.hash = "message-" + evidence.message_index;
  }
  return url.toString();
}


export function partitionCanonicalMemories(memories: CanonicalMemory[]): {
  active: CanonicalMemory[];
  rejected: CanonicalMemory[];
} {
  return {
    active: memories.filter((memory) => memory.status !== "retracted"),
    rejected: memories.filter((memory) => memory.status === "retracted")
  };
}

export function toggleCanonicalMemoryReviewReason(selected: string[], reason: string): string[] {
  return selected.includes(reason)
    ? selected.filter((value) => value !== reason)
    : [...selected, reason];
}

export function canonicalMemoryCardTone(memory: CanonicalMemory): "is-approved" | "is-rejected" | "" {
  if (memory.status === "retracted") return "is-rejected";
  if (memory.feedback?.rating === "agree") return "is-approved";
  return "";
}


export function canonicalMemoryReviewPayload(
  rating: "agree" | "disagree",
  reasons: string[],
  comment: string
): { rating: "agree" | "disagree"; reasons: string[]; comment: string | null } {
  return {
    rating,
    reasons,
    comment: comment.trim() || null
  };
}
