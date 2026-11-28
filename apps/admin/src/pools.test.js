import assert from "node:assert/strict";
import test from "node:test";
import {
  esc, nameOf, pairStatusLabel, pickProgressLabel, planChanges, readinessLine, renderPairs, renderPickResult, renderPoolList, renderSuggestions, toLocalInput, unreachedLines,
  weekdayName,
} from "./pools.js";

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

test("the pick button says how far the server's job is, and the result names pairs it could not check", () => {
  assert.equal(pickProgressLabel({ status: "queued", progress: { passes: 0, judged: 0, left: null } }), "Picking… (waiting to start)");
  assert.equal(pickProgressLabel({ status: "running", progress: { passes: 2, judged: 40, left: 12 } }), "Picking… 40 checked, 12 left");
  const html = renderPickResult({ pairs: [{ user_a: "u1", user_b: "u2", fit: "yes" }], judged: 3, not_judged: [{ user_a: "u1", user_b: "u2", why: "the judge call kept failing" }] }, view);
  assert.match(html, /Pick done: 1 pairs proposed, 3 checks run/);
  assert.match(html, /Not checked/);
  assert.equal(renderPickResult(null, view), "");
});

test("a pair says who was not reached and offers to send again once Omi stopped trying", () => {
  const asked = { id: "pr2", user_a: "u1", user_b: "u2", status: "asked", check: { fit: "yes" }, plan: { place: null, when: null }, undelivered: { u2: { step: "match_ask", why: "channel_failed", gave_up: true } } };
  assert.deepEqual(unreachedLines(asked, view), ["Aman did not get the ask: WhatsApp or Telegram refused the message."]);
  const html = renderPairs({ ...view, pairs: [asked] });
  assert.match(html, /Not reached/);
  assert.match(html, /data-resend="pr2"/);
  assert.doesNotMatch(html, /Plan:/); // an asked pair has a plan record but no place or time
  assert.doesNotMatch(html, /pool-set-plan/); // a plan is set once both said hi
  // Still being tried: say so, and no button yet.
  const trying = { ...asked, undelivered: { u2: { step: "match_intro", why: "no_chat", gave_up: false } } };
  assert.deepEqual(unreachedLines(trying, view), ["Aman did not get the introduction: they have no chat with Omi yet. Omi is trying again."]);
  assert.doesNotMatch(renderPairs({ ...view, pairs: [trying] }), /data-resend/);
  // Over: the line stays, sending again would do nothing.
  assert.doesNotMatch(renderPairs({ ...view, pairs: [{ ...asked, status: "expired" }] }), /data-resend/);
  assert.deepEqual(unreachedLines({ undelivered: {} }, view), []);
  assert.doesNotMatch(renderPairs(view), /Not reached/);
});

test("an introduced pair shows its plan and a form to set or change it", () => {
  const bare = { id: "pr3", user_a: "u1", user_b: "u2", status: "introduced", check: { fit: "yes" }, plan: { place: null, when: null, meet_at: null }, undelivered: {} };
  const empty = renderPairs({ ...view, pairs: [bare] });
  assert.match(empty, /No place or time set yet/);
  assert.match(empty, /class="pool-set-plan" data-pair-id="pr3"/);
  assert.match(empty, />Set plan</);
  const planned = renderPairs({ ...view, pairs: [{ ...bare, plan: { place: 'Chai "Point"', when: "Sunday 6pm", meet_at: "2026-12-06T12:30:00Z" } }] });
  assert.match(planned, /<strong>Plan:<\/strong> Chai &quot;Point&quot;, Sunday 6pm/);
  assert.match(planned, />Change plan</);
  assert.match(planned, /value="Chai &quot;Point&quot;"/);
  assert.match(planned, new RegExp(`value="${toLocalInput("2026-12-06T12:30:00Z")}"`));
});

test("the plan form sends only what changed", () => {
  const before = { place: "Chai Point", when: "Sunday 6pm", meet_at: "2026-12-06T18:00" };
  assert.deepEqual(planChanges(before, { ...before }), {});
  assert.deepEqual(planChanges(before, { ...before, place: " Chai Point " }), {});
  assert.deepEqual(planChanges(before, { ...before, when: "Monday 7pm" }), { when: "Monday 7pm" });
  assert.deepEqual(planChanges(before, { ...before, place: "" }), { place: null }); // emptied: cleared
  assert.deepEqual(planChanges(before, { ...before, meet_at: "2026-12-07T19:00" }), { meet_at: new Date("2026-12-07T19:00").toISOString() });
  assert.deepEqual(planChanges(before, { ...before, meet_at: "" }), { meet_at: null });
  assert.deepEqual(planChanges({}, { place: "Blue Tokai", when: "", meet_at: "" }), { place: "Blue Tokai" });
  assert.equal(toLocalInput(""), "");
  assert.equal(toLocalInput("not a date"), "");
  assert.equal(new Date(toLocalInput("2026-12-06T12:30:00Z")).toISOString(), "2026-12-06T12:30:00.000Z"); // round trip in any zone
});
