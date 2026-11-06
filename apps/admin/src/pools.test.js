import assert from "node:assert/strict";
import test from "node:test";
import { esc, nameOf, pairStatusLabel, readinessLine, renderPairs, renderPoolList, renderSuggestions, weekdayName } from "./pools.js";

const view = {
  pool: { id: "p1", name: "Sunrise", join_code: "ABCDEF", match_weekday: 5 },
  members: [
    { user_id: "u1", name: "Riya", readiness: { ready: true } },
    { user_id: "u2", name: "Aman", readiness: { ready: false, milestone: "basics", facts: { missing: ["area", "food"] } } },
  ],
  ready_count: 1,
  pairs: [{ id: "pr1", user_a: "u1", user_b: "u2", status: "proposed", created_at: "2026-11-06T10:00:00Z", check: { fit: "yes", comparable: ["humor", "interests"], reasons: ["Both laugh at puns."], difference: "She plans; he wings it.", icebreaker: "Worst pun?" } }],
  suggestions: [],
};

test("readinessLine says what is missing in plain words", () => {
  assert.equal(readinessLine({ ready: true }), "Ready");
  assert.equal(readinessLine(view.members[1].readiness), "vibe at basics · needs where they live");
  assert.equal(readinessLine({ ready: false, milestone: "ready_to_match", facts: { missing: [] } }), "Not ready");
});

test("labels", () => {
  assert.equal(weekdayName(5), "Saturday");
  assert.equal(pairStatusLabel("still_talking"), "Still talking");
  assert.equal(nameOf(view, "u2"), "Aman");
  assert.equal(esc("<b>&</b>"), "&lt;b&gt;&amp;&lt;/b&gt;");
});

test("renderPairs shows the check and an introduce form only while proposed", () => {
  const html = renderPairs(view);
  assert.match(html, /Riya &amp; Aman/);
  assert.match(html, /Fit: yes/);
  assert.match(html, /Both laugh at puns\./);
  assert.match(html, /class="pool-introduce"/);
  const introduced = renderPairs({ ...view, pairs: [{ ...view.pairs[0], status: "introduced", plan: { place: "Blue Tokai", when: "Saturday 6 pm" } }] });
  assert.doesNotMatch(introduced, /class="pool-introduce"/);
  assert.match(introduced, /Plan:<\/strong> Blue Tokai, Saturday 6 pm/);
});

test("renderSuggestions explains an empty list and never shows a percentage", () => {
  assert.match(renderSuggestions(view), /1 ready\. Pairs need at least two/);
  const html = renderSuggestions({ ...view, suggestions: [{ user_a: "u1", user_b: "u2", score: 73, comparable: 4 }] });
  assert.match(html, /data-propose="u1\|u2"/);
  assert.doesNotMatch(html, /73/);
  assert.doesNotMatch(html, /%/);
});

test("renderPoolList marks the open pool", () => {
  const html = renderPoolList([view.pool, { id: "p2", name: "Batch", join_code: "ZZZZZZ", match_weekday: 1 }], "p2");
  assert.match(html, /data-pool-id="p2" tabindex="0"/);
  assert.match(html, /class="pool-row is-selected" data-pool-id="p2"/);
  assert.match(html, /Tuesdays/);
});
