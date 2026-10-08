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

// A memory's key as a plain label: "study_topic_current" -> "Study topic (current)".
const KEY_QUALIFIERS = new Set(["current", "previous", "past", "old", "new", "recent", "planned", "future"]);
export function memoryLabel(key: string): string {
  const words = key.replaceAll("_", " ").replaceAll("-", " ").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const last = words[words.length - 1];
  const qualifier = words.length > 1 && KEY_QUALIFIERS.has(last) ? words.pop() : "";
  const text = words.join(" ");
  const label = text ? text[0].toUpperCase() + text.slice(1) : "";
  return qualifier ? `${label} (${qualifier})` : label;
}

// What Omi remembers, as readable lines: a plain value stays one line; a structured value becomes
// one short "Label: value" line per part instead of "likes: x · favorite parts: y".
export function memoryValueLines(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    const text = value.map(canonicalMemoryValueText).filter(Boolean).join(", ");
    return text ? [text] : [];
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = canonicalMemoryValueText(item);
        return text ? `${memoryLabel(key)}: ${text}` : "";
      })
      .filter(Boolean);
  }
  const text = String(value).trim();
  return text ? [text] : [];
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


// Current: what Omi uses now. Old: replaced by a newer memory, or past its end date; kept as
// history. Rejected: marked not true by the user.
export function partitionCanonicalMemories(
  memories: CanonicalMemory[],
  now: Date = new Date()
): {
  active: CanonicalMemory[];
  old: CanonicalMemory[];
  rejected: CanonicalMemory[];
} {
  const isOld = (memory: CanonicalMemory) =>
    memory.status === "superseded" || (memory.status !== "retracted" && hasEnded(memory, now));
  return {
    active: memories.filter((memory) => memory.status !== "retracted" && !isOld(memory)),
    old: memories.filter(isOld),
    rejected: memories.filter((memory) => memory.status === "retracted")
  };
}

function hasEnded(memory: CanonicalMemory, now: Date): boolean {
  if (!memory.valid_until) return false;
  const ends = new Date(memory.valid_until);
  return !Number.isNaN(ends.getTime()) && ends <= now;
}

// "Replaced by Jaipur on 3 Oct" or "Ended on 5 Oct", for a memory in the old section.
export function oldMemoryNote(memory: CanonicalMemory, all: CanonicalMemory[]): string {
  const day = (iso?: string | null) =>
    iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
  const newer = all.find((item) => item.supersedes_memory_id === memory.id);
  if (memory.status === "superseded") {
    const value = newer ? canonicalMemoryValueText(newer.value) : "";
    const when = day(newer?.created_at || memory.updated_at);
    return ["Replaced", value ? `by ${value}` : "", when ? `on ${when}` : ""].filter(Boolean).join(" ");
  }
  const ended = day(memory.valid_until);
  return ended ? `Ended on ${ended}` : "No longer current";
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
