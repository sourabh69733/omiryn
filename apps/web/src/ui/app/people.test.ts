import assert from "node:assert/strict";
import test from "node:test";
import type { MatchCard } from "./matches";
import { clusterClass, dayLabel, imageProblem, isBigEmoji, mergeMessages, newestId, pairFromPath, peopleRows, personPath, previewLine, startsDay, totalUnread, unreadLabel, type PersonMessage } from "./people";

const card = (pair_id: string, extra: Partial<MatchCard> = {}): MatchCard => ({
  pair_id, status: "introduced", name: pair_id, reasons: [], difference: null, icebreaker: null, plan: null, asked_at: "2026-11-10T10:00:00Z", answer_by: null, ...extra,
});
const chat = (extra: Partial<NonNullable<MatchCard["chat"]>> = {}) => ({ open: true, messages: 0, unread: 0, last_at: null, ...extra });
const message = (id: number, mine: boolean, at: string, extra: Partial<PersonMessage> = {}): PersonMessage => ({ id, mine, text: `m${id}`, created_at: at, ...extra });

test("only people with a chat are listed, newest activity first", () => {
  const rows = peopleRows([
    card("asked", { status: "asked", chat: null }),
    card("old", { chat: chat({ last_at: "2026-11-11T09:00:00Z", messages: 3 }) }),
    card("quiet", { introduced_at: "2026-11-12T09:00:00Z", chat: chat() }),
    card("new", { chat: chat({ last_at: "2026-11-13T09:00:00Z", messages: 1 }) }),
    card("blocked", { status: "blocked", chat: chat({ open: false, messages: 4, last_at: "2026-11-13T10:00:00Z" }) }),
    card("closed-empty", { status: "declined", chat: chat({ open: false }) }),
  ]);
  assert.deepEqual(rows.map((row) => row.pair_id), ["new", "quiet", "old"]);
});

test("the row shows the last message, whose it was, and how many are unread", () => {
  assert.equal(previewLine(card("a", { chat: chat({ last_text: "chai on Sunday?", last_mine: false }) })), "chai on Sunday?");
  assert.equal(previewLine(card("a", { chat: chat({ last_text: "sure", last_mine: true }) })), "You: sure");
  assert.equal(previewLine(card("a", { chat: chat() })), "You both said hi. Say something.");
  assert.equal(previewLine(card("a", { status: "declined", chat: chat({ open: false }) })), "Chat closed");
  assert.equal(previewLine(card("a", { chat: null })), "");
  assert.deepEqual([unreadLabel(0), unreadLabel(undefined), unreadLabel(3), unreadLabel(12)], ["", "", "3", "9+"]);
  assert.equal(totalUnread([card("a", { chat: chat({ unread: 2 }) }), card("b", { chat: null }), card("c", { chat: chat({ unread: 5 }) })]), 7);
});

test("fetched messages merge by id and replace their pending bubble", () => {
  const shown = [message(1, false, "2026-11-13T09:00:00Z"), message(-1, true, "2026-11-13T09:01:00Z", { pending: true, client_id: "c1" }), message(-2, true, "2026-11-13T09:02:00Z", { pending: true, client_id: "c2" })];
  const merged = mergeMessages(shown, [message(2, true, "2026-11-13T09:01:05Z", { client_id: "c1" }), message(1, false, "2026-11-13T09:00:00Z")]);
  assert.deepEqual(merged.map((m) => m.id), [1, 2, -2]);
  assert.equal(newestId(merged), 2);
  assert.equal(newestId([]), 0);
});

test("bubbles cluster by person and a date line starts each day", () => {
  const rows = [message(1, false, "2026-11-12T09:00:00Z"), message(2, false, "2026-11-12T09:05:00Z"), message(3, true, "2026-11-12T09:06:00Z"), message(4, true, "2026-11-13T09:00:00Z")];
  assert.deepEqual(rows.map((_, index) => clusterClass(rows, index)), ["cluster-start", "cluster-end same-cluster", "cluster-single", "cluster-single"]);
  assert.deepEqual(rows.map((_, index) => startsDay(rows, index)), [true, false, false, true]);
  const now = new Date("2026-11-13T12:00:00Z");
  assert.equal(dayLabel("2026-11-13T09:00:00Z", now), "Today");
  assert.equal(dayLabel("2026-11-12T09:00:00Z", now), "Yesterday");
});

test("a person's chat has its own address", () => {
  assert.equal(personPath("abc-123"), "/people/abc-123");
  assert.equal(pairFromPath("/people/abc-123"), "abc-123");
  assert.equal(pairFromPath("/matches"), null);
});

test("a message of one to three emoji is shown large; words or more are not", () => {
  assert.deepEqual(["😂", "❤️🔥", "👍🏽 👍🏽 👍🏽", "🇮🇳"].map(isBigEmoji), [true, true, true, true]);
  assert.deepEqual(["", "ok 😂", "😂😂😂😂", "123", ":)"].map(isBigEmoji), [false, false, false, false, false]);
});

test("only pictures the server takes can be picked", () => {
  assert.equal(imageProblem({ type: "image/png", size: 5_000_000 }), "");
  assert.equal(imageProblem({ type: "image/gif", size: 1_000_000 }), "");
  assert.match(imageProblem({ type: "image/gif", size: 6_000_000 }), /GIF is too big/);
  assert.match(imageProblem({ type: "application/pdf", size: 10 }), /JPG, PNG, WebP or GIF/);
});
