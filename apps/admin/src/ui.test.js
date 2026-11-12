import assert from "node:assert/strict";
import test from "node:test";
import { ago, barChart, delta, esc, ms, pct, pill, table, usd } from "./ui.js";
import { filterPeople } from "./pages/people.js";
import { kindLabel } from "./pages/usage.js";
import { view as dashboardView } from "./pages/dashboard.js";

test("formats read well at tiny and large sizes", () => {
  assert.equal(usd(0), "$0");
  assert.equal(usd(0.00123), "$0.0012");
  assert.equal(usd(0.0342), "$0.034");
  assert.equal(usd(12.5), "$12.50");
  assert.equal(ms(850), "850ms");
  assert.equal(ms(7682), "7.7s");
  assert.equal(pct(1, 3), "33%");
  assert.equal(pct(1, 200), "0.5%");
  assert.equal(pct(0, 0), "0%");
});

test("ago says how long ago in words", () => {
  const now = Date.parse("2026-11-12T12:00:00Z");
  assert.equal(ago("2026-11-12T11:58:00Z", now), "2 min ago");
  assert.equal(ago("2026-11-12T07:00:00Z", now), "5 h ago");
  assert.equal(ago("2026-11-11T10:00:00Z", now), "yesterday");
  assert.equal(ago(null, now), "never");
});

test("delta colours by direction and flips for costs", () => {
  assert.match(delta(12, 10), /class="delta up">▲ 20%/);
  assert.match(delta(8, 10), /class="delta down">▼ 20%/);
  assert.match(delta(12, 10, { goodWhenUp: false }), /class="delta down"/);
  assert.match(delta(3, 0), /new/);
});

test("pills, tables and charts escape what they show", () => {
  assert.match(pill("failed"), /pill bad/);
  assert.match(pill("done"), /pill good/);
  const html = table([{ label: "Name", cell: (row) => esc(row.name) }], [{ name: "<b>x</b>" }]);
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.match(table([], []), /Nothing here yet/);
  const chart = barChart([{ date: "2026-11-11", replies: 3, failed: 1 }, { date: "2026-11-12", replies: 0, failed: 0 }], [{ key: "replies", label: "Replies" }, { key: "failed", label: "Failed", tone: "bad" }]);
  assert.match(chart, /<title>11 Nov: Replies 3, Failed 1<\/title>/);
  assert.match(chart, /class="bar bad"/);
});

test("people filter by search and activity, and sort", () => {
  const now = Date.parse("2026-11-12T12:00:00Z");
  const people = [
    { user_id: "a1", display_name: "Riya", place: "Pune", last_active_at: "2026-11-12T10:00:00Z", replies: 4, failed_replies: 0, memories: 3 },
    { user_id: "b2", display_name: "Aman", place: "Delhi", last_active_at: "2026-10-01T10:00:00Z", replies: 9, failed_replies: 2, memories: 0 },
  ];
  assert.deepEqual(filterPeople(people, { search: "pun" }, now).map((p) => p.user_id), ["a1"]);
  assert.deepEqual(filterPeople(people, { filter: "quiet" }, now).map((p) => p.user_id), ["b2"]);
  assert.deepEqual(filterPeople(people, { filter: "failures" }, now).map((p) => p.user_id), ["b2"]);
  assert.deepEqual(filterPeople(people, { sort: "replies" }, now).map((p) => p.user_id), ["b2", "a1"]);
});

test("dashboard says all clear or lists what needs a look", () => {
  const base = { kpis: {}, omi: {}, health: {}, daily: [], recent_users: [] };
  assert.match(dashboardView({ ...base, attention: [] }), /All clear/);
  const html = dashboardView({ ...base, attention: [{ level: "bad", title: "Failed replies today", detail: "timeout", route: "/usage", count: 2 }] });
  assert.match(html, /href="\/usage" data-link/);
  assert.match(html, /Failed replies today/);
  assert.equal(kindLabel("chat_reply"), "Omi reply");
});
