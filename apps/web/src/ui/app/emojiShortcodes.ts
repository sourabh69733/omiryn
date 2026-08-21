export type EmojiQuery = {
  start: number;
  end: number;
  query: string;
};

export type EmojiRecord = {
  group?: number;
  hexcode: string;
  label: string;
  tags?: string[];
  unicode: string;
};

export type EmojiSuggestion = {
  label: string;
  shortcode: string;
  unicode: string;
};

export function findEmojiQuery(value: string, cursor: number): EmojiQuery | null {
  const match = /(^|\s):([a-z0-9_+-]{2,})$/i.exec(value.slice(0, cursor));
  if (!match) return null;
  const start = match.index + match[1].length;
  return { start, end: cursor, query: match[2].toLowerCase() };
}

export function searchEmojiSuggestions(query: string, emojis: EmojiRecord[], limit = 6): EmojiSuggestion[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (normalizedQuery.length < 2) return [];

  return emojis
    .filter((emoji) => emoji.group !== undefined && emoji.unicode && emoji.label)
    .map((emoji, index) => {
      const terms = [...(emoji.tags || []), emoji.label].map((term) => term.toLowerCase());
      const exact = terms.findIndex((term) => term === normalizedQuery);
      const prefix = terms.findIndex((term) => term.startsWith(normalizedQuery));
      const partial = terms.findIndex((term) => term.includes(normalizedQuery));
      const rank = exact >= 0 ? 0 : prefix >= 0 ? 1 : partial >= 0 ? 2 : -1;
      const matchedTerm = terms[exact >= 0 ? exact : prefix >= 0 ? prefix : partial];
      return { emoji, index, rank, matchedTerm };
    })
    .filter((result) => result.rank >= 0)
    .sort((left, right) => left.rank - right.rank || left.index - right.index)
    .slice(0, limit)
    .map(({ emoji, matchedTerm }) => ({
      label: emoji.label,
      shortcode: shortcodeFor(matchedTerm || emoji.label),
      unicode: emoji.unicode
    }));
}

export function replaceEmojiQuery(value: string, query: EmojiQuery, unicode: string) {
  const nextValue = `${value.slice(0, query.start)}${unicode}${value.slice(query.end)}`;
  return { value: nextValue, cursor: query.start + unicode.length };
}

export async function loadEmojiRecords(): Promise<EmojiRecord[]> {
  const module = await import("emojibase-data/en/compact.json");
  return module.default as EmojiRecord[];
}

function shortcodeFor(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
