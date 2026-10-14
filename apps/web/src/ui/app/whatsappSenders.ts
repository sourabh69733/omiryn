// Reads a WhatsApp export in the browser just enough to ask "Which one is you?".
// The server does the real parsing; this only finds who wrote the lines.

// "13/09/2026, 9:15 pm - Riya: hi" (Android) and "[13/09/26, 9:15:02 PM] Riya: hi" (iPhone).
const LINE = /^\[?\d{1,2}[/-]\d{1,2}[/-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?[Mm]\.?)?\]?\s(?:[-–]\s)?([^:]{1,120}):\s/;

export type ChatSender = { name: string; count: number };

// Everyone who wrote in the chat, most messages first.
export function chatSenders(text: string): ChatSender[] {
  const counts = new Map<string, number>();
  for (const raw of text.split(/\r?\n/)) {
    const match = LINE.exec(raw.replace(/^‎/, "").trim());
    if (!match) continue;
    const name = match[1].replace(/‎/g, "").trim();
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
}

// "WhatsApp Chat with Riya.txt" -> "Riya"; otherwise the person who wrote most besides the user.
export function chatTitle(fileName: string, senders: ChatSender[], me: string | null): string {
  const fromFile = fileName.replace(/\.txt$/i, "").replace(/^WhatsApp Chat( with| -)?\s*/i, "").trim();
  if (fromFile && fromFile.toLowerCase() !== "_chat" && fromFile !== fileName.replace(/\.txt$/i, "")) return fromFile;
  return senders.find((sender) => sender.name !== me)?.name || "WhatsApp chat";
}
