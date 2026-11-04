import assert from "node:assert/strict";
import test from "node:test";
import { NO_TYPING_SIGNAL, nextTypingSignal, TYPING_SIGNAL_EVERY_MS } from "./typingSignal";

const start = 1_000_000;

test("nothing is sent unless a reply is pending", () => {
  assert.equal(nextTypingSignal(NO_TYPING_SIGNAL, "hel", false, start).signal, null);
});

test("the first keystroke signals at once, then at most once a second", () => {
  const first = nextTypingSignal(NO_TYPING_SIGNAL, "h", true, start);
  assert.equal(first.signal, "typing");
  const soon = nextTypingSignal(first.state, "he", true, start + TYPING_SIGNAL_EVERY_MS - 1);
  assert.equal(soon.signal, null);
  assert.equal(nextTypingSignal(soon.state, "hel", true, start + TYPING_SIGNAL_EVERY_MS).signal, "typing");
});

test("clearing the box says stopped, once, and only after a signal", () => {
  const typing = nextTypingSignal(NO_TYPING_SIGNAL, "h", true, start);
  const cleared = nextTypingSignal(typing.state, "", true, start + 10);
  assert.equal(cleared.signal, "stopped");
  assert.equal(nextTypingSignal(cleared.state, "", true, start + 20).signal, null);
  assert.equal(nextTypingSignal(NO_TYPING_SIGNAL, "  ", true, start).signal, null);
});

test("typing again right after clearing signals at once", () => {
  const typing = nextTypingSignal(NO_TYPING_SIGNAL, "h", true, start);
  const cleared = nextTypingSignal(typing.state, "", true, start + 10);
  assert.equal(nextTypingSignal(cleared.state, "n", true, start + 20).signal, "typing");
});
