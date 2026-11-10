// Links inside a chat bubble, and the app pages Omi can put a button for.
import type { Page } from "./types";

export type TextPart = { text: string; href?: string };

// http(s) only; trailing punctuation that usually ends a sentence stays outside the link.
const URL_PATTERN = /https?:\/\/[^\s<>"]+/g;
const TRAILING = /[.,!?;:)\]}'"]+$/;

export function splitLinks(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    const start = match.index ?? 0;
    const raw = match[0];
    const trail = raw.match(TRAILING)?.[0] ?? "";
    const url = trail ? raw.slice(0, -trail.length) : raw;
    if (!isSafeUrl(url)) continue;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ text: url, href: url });
    last = start + url.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts.length ? parts : [{ text }];
}

function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (parsed.protocol === "https:" || parsed.protocol === "http:") && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

// What the button under Omi's reply says, for each page it may open.
export const PAGE_BUTTON_LABELS: Partial<Record<Page, string>> = {
  privacy: "Open Privacy",
  memories: "Open Memories",
  vibe: "Open Vibe",
  matches: "Open Matches",
  profile: "Open Profile",
};

export function pageButton(page: string | undefined): { page: Page; label: string } | null {
  if (!page || !(page in PAGE_BUTTON_LABELS)) return null;
  const known = page as Page;
  return { page: known, label: PAGE_BUTTON_LABELS[known]! };
}
