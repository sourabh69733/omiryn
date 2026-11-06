import assert from "node:assert/strict";
import test from "node:test";
import { deadlineLabel, matchDayLabel, matchesLabel, needsList, poolLine, splitMatches, statusLine, type MatchCard, type MatchReadiness } from "./matches";

const card = (status: MatchCard["status"], extra: Partial<MatchCard> = {}): MatchCard => ({
  pair_id: `p-${status}`, status, name: "Riya", pool_id: "pool-1", reasons: [], difference: null, icebreaker: null, plan: null,
  asked_at: "2026-11-05T10:00:00Z", answer_by: "2026-11-07T10:00:00Z", ...extra,
});

test("splitMatches keeps the card for the user, the waiting ones and the people; hides passes and expiries", () => {
  const split = splitMatches([card("asked"), card("waiting"), card("introduced"), card("met"), card("still_talking"), card("no_show"), card("declined"), card("expired")]);
  assert.equal(split.open.length, 1);
  assert.equal(split.waiting.length, 1);
  assert.deepEqual(split.people.map((c) => c.status), ["introduced", "met", "still_talking", "no_show"]);
});

test("matchesLabel reads the most pressing state first", () => {
  assert.equal(matchesLabel(true, splitMatches([card("asked")])), "1 for you");
  assert.equal(matchesLabel(true, splitMatches([card("waiting"), card("waiting", { pair_id: "p2" })])), "2 waiting");
  assert.equal(matchesLabel(true, splitMatches([])), "Looking");
  assert.equal(matchesLabel(false, splitMatches([])), "Not yet");
});

test("deadlineLabel counts down from two days to today", () => {
  const now = new Date("2026-11-05T10:00:00Z");
  assert.equal(deadlineLabel("2026-11-07T10:00:00Z", now), "You have two days");
  assert.equal(deadlineLabel("2026-11-06T18:00:00Z", now), "Closes tomorrow");
  assert.equal(deadlineLabel("2026-11-05T22:00:00Z", now), "Closes today");
  assert.equal(deadlineLabel(null, now), null);
  assert.equal(deadlineLabel("not a date", now), null);
});

test("statusLine says what Omi is doing for each person", () => {
  assert.equal(statusLine(card("introduced", { plan: { place: "Blue Tokai", when: "Saturday 6 pm" } })), "Meeting Saturday 6 pm · Omi will remind you");
  assert.equal(statusLine(card("introduced")), "You both said hi · Omi is setting a time");
  assert.equal(statusLine(card("still_talking")), "Met · still talking");
  assert.equal(statusLine(card("no_show")), "Didn't happen");
});

test("matchDayLabel uses Python weekday numbers", () => {
  assert.equal(matchDayLabel(0), "Mondays");
  assert.equal(matchDayLabel(5), "Saturdays");
});

test("poolLine prefers an open intro, then waiting, else looking", () => {
  const pool = { id: "pool-1", name: "Sunrise", match_weekday: 5 };
  assert.equal(poolLine(pool, [], [card("asked")]), "1 intro");
  assert.equal(poolLine(pool, [], [card("waiting")]), "Waiting");
  assert.equal(poolLine(pool, [{ id: "x", pool_id: "pool-1", status: "proposed", created_at: "" }], []), "Waiting");
  assert.equal(poolLine(pool, [], []), "Looking");
});

test("needsList puts what is missing first, in plain words, and what is clear after", () => {
  const readiness: MatchReadiness = {
    ready: false, milestone: "basics", private_allowed: false, blockers: ["not known yet: area, free time"],
    areas: { clear: ["humor"], mentioned: [], missing: [] }, facts: { known: { food: "veg" }, missing: ["area", "free_time"] },
  };
  const items = needsList(readiness);
  assert.deepEqual(items.map((i) => [i.label, i.done]), [
    ["A fuller sense of you", false], ["Where you live", false], ["When you're free", false], ["What you eat", true],
  ]);
  assert.match(items[0].hint, /The basics/);
});
