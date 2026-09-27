import assert from "node:assert/strict";
import test from "node:test";
import { typingAfterEvent } from "./agentTyping";
import { nextBubbleDelay } from "./bubbleReveal";

const typing = (active: boolean, id = "c1") => ({ type: "agent.typing", scope: "conversation" as const, scope_id: id, version: 1, payload: { active } });

test("typing starts and stops for the conversation that sent it", () => {
  assert.equal(typingAfterEvent(typing(true), null), "c1");
  assert.equal(typingAfterEvent(typing(false), "c1"), null);
  assert.equal(typingAfterEvent(typing(false, "c2"), "c1"), "c1");
});

test("an arriving companion message ends typing; a user message does not", () => {
  const created = (role: string) => ({ type: "message.created", scope: "conversation" as const, scope_id: "c1", version: 1, payload: { message: { role } } });
  assert.equal(typingAfterEvent(created("assistant"), "c1"), null);
  assert.equal(typingAfterEvent(created("user"), "c1"), "c1");
});

test("parts of one automatic story part are paced like a normal reply", () => {
  const at = "2026-09-27T10:00:00+00:00";
  const messages = [
    { role: "assistant", content: "earlier part", created_at: "2026-09-27T09:59:00+00:00" },
    { role: "assistant", content: "The light was a boat.", created_at: at },
    { role: "assistant", content: "Someone waved from it.", created_at: at }
  ];
  assert.equal(nextBubbleDelay(messages, 1), 0);
  assert.ok(nextBubbleDelay(messages, 2) > 0);
});
