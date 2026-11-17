import assert from "node:assert/strict";
import test from "node:test";
import { type ChatRead, type ReadCounts, type ReadSide, dateRange, duration, hourLabel, readButton, readFromPath, readLabel, readPath, shareLines, sideFacts, versus, wrapText } from "./chatRead";

const side = (extra: Partial<ReadSide> = {}): ReadSide => ({
  messages: 10, words: 60, words_per_message: 6, starts: 2, last_words: 2, double_texts: 1, reply_median_seconds: 120, laughs: 3, questions: 2, night_messages: 0, top_emoji: [], ...extra,
});
const counts = (me: Partial<ReadSide> = {}, them: Partial<ReadSide> = {}, extra: Partial<ReadCounts> = {}): ReadCounts => ({
  from: "2026-03-01", to: "2026-06-20", span_days: 112, days_talked: 80, longest_streak_days: 21, longest_silence_days: 6, longest_silence_from: "2026-04-02",
  messages: 20, busiest_hour: 21, busiest_weekday: "Sunday", busiest_day: { date: "2026-05-01", messages: 140 }, first_message: { who: "them", date: "2026-03-01", text: "hi" },
  me: side(me), them: side(them), ...extra,
});

test("a read has its own address", () => {
  assert.equal(readPath("abc 1"), "/read/abc%201");
  assert.equal(readFromPath("/read/abc%201"), "abc 1");
  assert.equal(readFromPath("/read/x/y"), "x");
  assert.equal(readFromPath("/memories"), null);
});

test("times are said the way a person would", () => {
  assert.equal(duration(40), "40 sec");
  assert.equal(duration(720), "12 min");
  assert.equal(duration(6600), "1 h 50 min");
  assert.equal(duration(7200), "2 h");
  assert.equal(duration(3 * 86400), "3 days");
  assert.equal(duration(null), "no replies");
  assert.deepEqual([0, 9, 12, 21].map(hourLabel), ["12 am", "9 am", "12 pm", "9 pm"]);
  assert.equal(dateRange("2026-03-01", "2026-06-20"), "1 Mar to 20 Jun 2026");
  assert.equal(dateRange("2025-12-30", "2026-01-02"), "30 Dec 2025 to 2 Jan 2026");
  assert.equal(dateRange("2026-03-01", "2026-03-01"), "1 Mar 2026");
});

test("each row says who leads; for replies the faster one leads", () => {
  const rows = versus(counts({ starts: 30, reply_median_seconds: 3600, laughs: 5, night_messages: 0 }, { starts: 10, reply_median_seconds: 120, laughs: 5, night_messages: 0 }));
  const by = Object.fromEntries(rows.map((row) => [row.id, row]));
  assert.deepEqual([by.starts.lead, by.starts.share, by.starts.me, by.starts.them], ["me", 75, "30 times", "10 times"]);
  assert.deepEqual([by.reply.lead, by.reply.me, by.reply.them], ["them", "1 h", "2 min"]);
  assert.ok(by.reply.share < 10);  // the bar shows how little of the waiting is on the slow side's partner
  assert.equal(by.laughs.lead, "even");
  assert.equal(by.night, undefined);  // nothing on either side: no row
  assert.equal(versus(counts({ reply_median_seconds: null }, { reply_median_seconds: 60 })).find((row) => row.id === "reply")?.lead, "them");
  assert.equal(versus(counts({ starts: 1 }, { starts: 1 })).find((row) => row.id === "starts")?.me, "1 time");
});

test("the small facts leave out what is not worth saying", () => {
  assert.deepEqual(sideFacts(counts()), [
    "Mostly around 9 pm, and Sundays more than other days.",
    "Busiest day: 1 May 2026, 140 messages.",
    "Longest quiet: 6 days, from 2 Apr 2026.",
  ]);
  assert.equal(sideFacts(counts({}, {}, { longest_silence_days: 1, busiest_day: { date: "2026-05-01", messages: 1 } })).length, 1);
});

test("the share picture names who does what, never more than four lines, and skips ties", () => {
  const read: Extract<ChatRead, { state: "ready" }> = {
    state: "ready", version: 1, me: "Aman", them: "Riya", written: null, built_at: "2026-11-16T10:00:00Z",
    counts: counts({ starts: 30, reply_median_seconds: 3600, laughs: 5, night_messages: 9, double_texts: 0, last_words: 1 }, { starts: 10, reply_median_seconds: 120, laughs: 5, night_messages: 1, double_texts: 4, last_words: 6 }),
  };
  assert.deepEqual(shareLines(read), ["Aman writes first", "Riya replies faster (2 min)", "Aman is up after midnight", "Riya writes again before a reply"]);
});

test("text wraps to a width and ends with a mark when it does not fit", () => {
  const measure = (line: string) => line.length;
  assert.deepEqual(wrapText("one two three four", 9, measure), ["one two", "three", "four"]);
  assert.deepEqual(wrapText("one two three four five six", 9, measure, 2), ["one two", "three…"]);
  assert.deepEqual(wrapText("", 9, measure), []);
});

test("the upload row shows a way into the read only when there can be one", () => {
  assert.equal(readButton("whatsapp_chat", "ready"), "open");
  assert.equal(readButton("whatsapp_chat", undefined), "open");  // an older upload: made on the first visit
  assert.equal(readButton("whatsapp_chat", "making"), "making");
  assert.equal(readButton("whatsapp_chat", "group_chat"), "none");
  assert.equal(readButton("whatsapp_chat", "too_short"), "none");
  assert.equal(readButton("notes", "ready"), "none");
  assert.equal(readLabel("Farheen Parvez"), "You & Farheen");
  assert.equal(readLabel("  ऋतु शर्मा"), "You & ऋतु");
  assert.equal(readLabel("+91 98765 43210"), "You two");
  assert.equal(readLabel("chat_2026.txt"), "You two");
  assert.equal(readLabel(undefined), "You two");
});
