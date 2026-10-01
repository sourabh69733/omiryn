import assert from "node:assert/strict";
import test from "node:test";
import { evidenceChatPath, milestoneFromEvent, saidLabel, vibeStepNote } from "./vibe";

const reached = (milestone: string, previous: string, id = "c1") => ({ type: "vibe.milestone", scope: "conversation" as const, scope_id: id, version: 1, payload: { milestone, previous } });

test("a new milestone in the open chat is shown", () => {
  assert.equal(milestoneFromEvent(reached("basics", "first_impressions"), "c1"), "basics");
  assert.equal(milestoneFromEvent(reached("first_impressions", "starting"), "c1"), "first_impressions");
});

test("other chats, other events and steps back are ignored", () => {
  assert.equal(milestoneFromEvent(reached("basics", "first_impressions", "c2"), "c1"), null);
  assert.equal(milestoneFromEvent(reached("starting", "first_impressions"), "c1"), null);
  assert.equal(milestoneFromEvent({ ...reached("basics", "starting"), type: "agent.typing" }, "c1"), null);
});

test("every milestone past starting has a note", () => {
  assert.equal(vibeStepNote("starting"), null);
  assert.ok(vibeStepNote("ready_to_match"));
});

test("proof links open the chat at that message", () => {
  assert.equal(evidenceChatPath({ conversation_id: "a b", message_index: 7 }), "/?conversation_id=a%20b#message-7");
});

test("the chip says how often it was said, counting days", () => {
  assert.equal(saidLabel(0, 0), "Said once");
  assert.equal(saidLabel(1, 1), "Said once");
  assert.equal(saidLabel(3, 1), "Said 3 times, one day");
  assert.equal(saidLabel(4, 2), "Said on 2 days");
});
