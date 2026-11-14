import assert from "node:assert/strict";
import test from "node:test";
import { ActiveTimer, IDLE_MS, RageClickDetector, describeTarget, signInErrorFromUrl } from "./experienceMetrics";

test("active time counts input gaps up to the idle limit and stops while hidden", () => {
  const timer = new ActiveTimer(0);
  timer.interact(10_000);
  timer.interact(100_000); // 90 s without input counts as 30 s
  assert.deepEqual(timer.read(100_000), { activeMs: 40_000, visibleMs: 100_000 });

  timer.hide(105_000);
  assert.deepEqual(timer.read(500_000), { activeMs: 45_000, visibleMs: 105_000 });

  timer.show(600_000);
  timer.interact(602_000);
  assert.deepEqual(timer.read(602_000), { activeMs: 47_000, visibleMs: 107_000 });
});

test("a tab left open counts at most the idle limit", () => {
  const timer = new ActiveTimer(0);
  assert.equal(timer.read(8 * 3_600_000).activeMs, IDLE_MS);
});

test("a timer started hidden counts nothing until shown", () => {
  const timer = new ActiveTimer(0, false);
  timer.interact(5_000);
  assert.deepEqual(timer.read(10_000), { activeMs: 0, visibleMs: 0 });
});

test("three quick clicks in one spot are a rage click; spread out or slow ones are not", () => {
  const detector = new RageClickDetector();
  assert.equal(detector.click(10, 10, 0), false);
  assert.equal(detector.click(12, 11, 200), false);
  assert.equal(detector.click(11, 9, 400), true);

  const slow = new RageClickDetector();
  slow.click(10, 10, 0);
  slow.click(10, 10, 900);
  assert.equal(slow.click(10, 10, 1800), false);

  const apart = new RageClickDetector();
  apart.click(10, 10, 0);
  apart.click(200, 10, 100);
  assert.equal(apart.click(400, 10, 200), false);
});

test("a click target is named by code, never by its text", () => {
  assert.equal(describeTarget({ tagName: "BUTTON", classList: Object.assign(["send-button", "big"], { length: 2 }) }), "button.send-button");
  assert.equal(describeTarget({ tagName: "DIV", classList: Object.assign([], { length: 0 }) }), "div");
  assert.equal(describeTarget(null), "unknown");
});

test("a failed Google sign-in is read from the return URL as a code", () => {
  assert.equal(signInErrorFromUrl({ search: "?error=access_denied&error_description=User+said+no", hash: "" }), "access_denied");
  assert.equal(signInErrorFromUrl({ search: "", hash: "#error=server_error&error_code=bad_oauth_state" }), "bad_oauth_state");
  assert.equal(signInErrorFromUrl({ search: "?conversation_id=1", hash: "" }), null);
});
