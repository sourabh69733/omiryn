// The read: what an uploaded chat says about the two people in it. Shapes follow
// GET /api/me/context-sources/<id>/chat-read; the helpers turn counts into the lines the page and
// the share picture show.

export type ReadSide = {
  messages: number;
  words: number;
  words_per_message: number;
  starts: number;
  last_words: number;
  double_texts: number;
  reply_median_seconds: number | null;
  laughs: number;
  questions: number;
  night_messages: number;
  top_emoji: string[];
};

export type ReadItem = { text: string; about?: string; lines: number[] };

export type ReadWritten = {
  headline: string;
  you_two: string;
  roles: { me: string; them: string };
  running_jokes: ReadItem[];
  keep_coming_back_to: ReadItem[];
  friction: ReadItem | null;
  green_flag: string;
  roast: string;
};

export type ReadCounts = {
  from: string;
  to: string;
  span_days: number;
  days_talked: number;
  longest_streak_days: number;
  longest_silence_days: number;
  longest_silence_from: string | null;
  messages: number;
  busiest_hour: number;
  busiest_weekday: string;
  busiest_day: { date: string; messages: number };
  first_message: { who: "me" | "them"; date: string; text: string };
  me: ReadSide;
  them: ReadSide;
};

export type ChatRead =
  | { state: "ready"; version: number; me: string; them: string; counts: ReadCounts; written: ReadWritten | null; built_at: string }
  | { state: "none" | "group_chat" | "too_short" | "no_chat" };

export const readPath = (sourceId: string) => `/read/${encodeURIComponent(sourceId)}`;

export function readFromPath(pathname: string): string | null {
  const match = /^\/read\/([^/]+)/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

/** "40 sec", "12 min", "1 h 50 min", "2 days". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "no replies";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

/** 0 -> "12 am", 21 -> "9 pm". */
export function hourLabel(hour: number): string {
  const h = ((hour % 24) + 24) % 24;
  return `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? "am" : "pm"}`;
}

export function dayText(day: string | null | undefined, withYear = false): string {
  if (!day) return "";
  const date = new Date(`${day}T12:00:00`);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}

/** "1 Mar to 4 Mar 2026"; one day when it started and ended on the same one. */
export function dateRange(from: string, to: string): string {
  if (from === to) return dayText(from, true);
  return `${dayText(from, from.slice(0, 4) !== to.slice(0, 4))} to ${dayText(to, true)}`;
}

export type Versus = {
  id: string;
  label: string;
  me: string;
  them: string;
  /** 0 to 100: the share of the bar that is "me". */
  share: number;
  lead: "me" | "them" | "even";
};

const count = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

/** The side-by-side rows, in the order the page shows them. A row with nothing on both sides is left out. */
export function versus(counts: ReadCounts): Versus[] {
  const { me, them } = counts;
  const more = (id: string, label: string, a: number, b: number, text: (n: number) => string): Versus | null =>
    a + b === 0 ? null : { id, label, me: text(a), them: text(b), share: Math.round((100 * a) / (a + b)), lead: a === b ? "even" : a > b ? "me" : "them" };
  const rows: (Versus | null)[] = [
    more("starts", "Writes first", me.starts, them.starts, (n) => count(n, "time")),
    replyRow(me.reply_median_seconds, them.reply_median_seconds),
    more("messages", "Messages", me.messages, them.messages, (n) => n.toLocaleString("en-IN")),
    more("words", "Words a message", me.words_per_message, them.words_per_message, (n) => String(n)),
    more("laughs", "Laughs", me.laughs, them.laughs, (n) => count(n, "time")),
    more("questions", "Asks questions", me.questions, them.questions, (n) => count(n, "time")),
    more("double_texts", "Writes again before a reply", me.double_texts, them.double_texts, (n) => count(n, "time")),
    more("night", "Up after midnight", me.night_messages, them.night_messages, (n) => count(n, "message")),
    more("last_words", "Gets the last word", me.last_words, them.last_words, (n) => count(n, "time")),
  ];
  return rows.filter((row): row is Versus => row !== null);
}

function replyRow(mine: number | null, theirs: number | null): Versus | null {
  if (mine === null && theirs === null) return null;
  // The faster one leads, so the bar shows the other's share of the waiting.
  const a = mine ?? 0, b = theirs ?? 0;
  const lead = mine === null ? "them" : theirs === null ? "me" : a === b ? "even" : a < b ? "me" : "them";
  return { id: "reply", label: "Replies in", me: duration(mine), them: duration(theirs), share: a + b ? Math.round((100 * b) / (a + b)) : 50, lead };
}

/** Small true lines under the numbers: when they talk, the busiest day, the longest quiet. */
export function sideFacts(counts: ReadCounts): string[] {
  const facts = [`Mostly around ${hourLabel(counts.busiest_hour)}, and ${counts.busiest_weekday}s more than other days.`];
  if (counts.busiest_day.messages > 1) facts.push(`Busiest day: ${dayText(counts.busiest_day.date, true)}, ${count(counts.busiest_day.messages, "message")}.`);
  if (counts.longest_silence_days >= 2) facts.push(`Longest quiet: ${count(counts.longest_silence_days, "day")}${counts.longest_silence_from ? `, from ${dayText(counts.longest_silence_from, true)}` : ""}.`);
  return facts;
}

/** Who leads a row, by name, for the share picture: "Riya writes first" style lines, at most four. */
export function shareLines(read: Extract<ChatRead, { state: "ready" }>): string[] {
  const name = (who: "me" | "them") => (who === "me" ? read.me : read.them);
  const by = Object.fromEntries(versus(read.counts).map((row) => [row.id, row]));
  const lines: string[] = [];
  const say = (id: string, text: (winner: string, row: Versus) => string) => {
    const row = by[id];
    if (row && row.lead !== "even") lines.push(text(name(row.lead), row));
  };
  say("starts", (winner) => `${winner} writes first`);
  say("reply", (winner, row) => `${winner} replies faster (${row.lead === "me" ? row.me : row.them})`);
  say("laughs", (winner) => `${winner} laughs more`);
  say("night", (winner) => `${winner} is up after midnight`);
  say("double_texts", (winner) => `${winner} writes again before a reply`);
  say("last_words", (winner) => `${winner} gets the last word`);
  return lines.slice(0, 4);
}

/** Break text into lines that fit a width, by a measuring function (canvas or a test's own). */
export function wrapText(text: string, maxWidth: number, measure: (line: string) => number, maxLines = 6): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure(next) > maxWidth) {
      lines.push(line);
      line = word;
      if (lines.length === maxLines) break;
    } else {
      line = next;
    }
  }
  if (line && lines.length < maxLines) lines.push(line);
  else if (line && lines.length === maxLines) lines[maxLines - 1] = `${lines[maxLines - 1].replace(/[.,;:!?]*$/, "")}…`;
  return lines;
}

const CARD = { width: 1080, height: 1350, pad: 84 };

/** Draw the share picture: names, the headline, a few lines of who does what, the roast. No
    message text and nothing from the chat itself: only what the read says. */
export function drawReadCard(canvas: HTMLCanvasElement, read: Extract<ChatRead, { state: "ready" }>): void {
  canvas.width = CARD.width;
  canvas.height = CARD.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  const paper = token("--paper", "#f3eee4"), ink = token("--ink", "#15120e"), muted = token("--muted", "#6b6257"), ember = token("--ember-deep", "#bc2e0f"), card = token("--card", "#ffffff");
  const display = `"Fraunces", Georgia, serif`, sans = `"Bricolage Grotesque", system-ui, sans-serif`, mono = `"JetBrains Mono", ui-monospace, monospace`;
  const width = CARD.width - 2 * CARD.pad;
  ctx.fillStyle = paper;
  ctx.fillRect(0, 0, CARD.width, CARD.height);
  ctx.textBaseline = "top";
  let y = CARD.pad;
  const write = (text: string, font: string, color: string, lineHeight: number, maxLines: number, x = CARD.pad, w = width) => {
    ctx.font = font;
    ctx.fillStyle = color;
    for (const line of wrapText(text, w, (value) => ctx.measureText(value).width, maxLines)) {
      ctx.fillText(line, x, y);
      y += lineHeight;
    }
  };
  write("THE READ", `500 26px ${mono}`, ember, 44, 1);
  write(`${read.me} & ${read.them}`, `500 92px ${display}`, ink, 104, 2);
  write(`${dateRange(read.counts.from, read.counts.to)} · ${read.counts.days_talked.toLocaleString("en-IN")} days · ${read.counts.messages.toLocaleString("en-IN")} messages`, `400 30px ${sans}`, muted, 58, 2);
  y += 18;
  if (read.written?.headline) {
    write(read.written.headline, `500 56px ${display}`, ink, 70, 3);
    y += 26;
  }
  const lines = shareLines(read);
  if (lines.length) {
    const top = y;
    const height = 44 + lines.length * 62;
    ctx.fillStyle = card;
    roundRect(ctx, CARD.pad, top, width, height, 32);
    ctx.fill();
    y = top + 30;
    for (const line of lines) write(line, `500 36px ${sans}`, ink, 62, 1, CARD.pad + 40, width - 80);
    y = top + height + 40;
  }
  if (read.written?.roast) {
    write("THE ROAST", `500 24px ${mono}`, ember, 44, 1);
    write(read.written.roast, `400 38px ${display}`, ink, 54, Math.max(2, Math.floor((CARD.height - CARD.pad - 70 - y) / 54)));
  }
  y = CARD.height - CARD.pad - 34;
  write("omiryn.com · what does your chat say?", `500 26px ${mono}`, muted, 34, 1);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
