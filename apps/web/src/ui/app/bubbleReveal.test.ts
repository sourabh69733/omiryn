import assert from "node:assert/strict";
import test from "node:test";
import { nextBubbleDelay } from "./bubbleReveal";

const at = "2026-09-23T15:30:00+00:00";

test("later bubbles of one reply wait, sized by length and capped", () => {
  const messages = [
    { role: "user", content: "tell me a story", created_at: at },
    { role: "assistant", content: "Once upon a time", created_at: at },
    { role: "assistant", content: "there was a tiny chai stall", created_at: at },
    { role: "assistant", content: "x".repeat(500), created_at: at },
  ];
  assert.equal(nextBubbleDelay(messages, 1), 0);
  assert.equal(nextBubbleDelay(messages, 2), 600 + 27 * 30);
  assert.equal(nextBubbleDelay(messages, 3), 2600);
});

test("user messages, separate replies and untimed messages show at once", () => {
  const messages = [
    { role: "assistant", content: "hey", created_at: at },
    { role: "assistant", content: "you there?", created_at: "2026-09-23T16:00:00+00:00" },
    { role: "user", content: "yes", created_at: at },
    { role: "assistant", content: "nice" },
    { role: "assistant", content: "ok" },
  ];
  assert.equal(nextBubbleDelay(messages, 0), 0);
  assert.equal(nextBubbleDelay(messages, 1), 0);
  assert.equal(nextBubbleDelay(messages, 2), 0);
  assert.equal(nextBubbleDelay(messages, 4), 0);
  assert.equal(nextBubbleDelay(messages, 9), 0);
});
