import type { ContextSource } from "./types";

// What deleting one upload removes, in the order the user would care about it.
export function uploadDeleteLines(source: ContextSource): string[] {
  const learned = source.metadata?.reading?.learned;
  return [
    "The chat you shared",
    learned ? `What Omi learned about you only from it (${learned} ${learned === 1 ? "thing" : "things"})` : "What Omi learned about you only from it",
    ...(source.digest?.summary || source.digest?.topics?.length ? ["Its summary and topics"] : []),
    ...(source.source_type === "whatsapp_chat" ? ["\"What it says about you two\""] : []),
  ];
}
