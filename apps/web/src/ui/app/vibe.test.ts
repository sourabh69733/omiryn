import assert from "node:assert/strict";
import test from "node:test";
import { evidenceChatPath, milestoneFromEvent, proofSummary, strengthLabel, vibeStepNote } from "./vibe";

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

test("the chip says New or Confirmed; the panel has the count", () => {
  assert.equal(strengthLabel("clear"), "Confirmed");
  assert.equal(strengthLabel("mentioned"), "New");
  assert.equal(proofSummary(1, 1), "From 1 of your messages");
  assert.equal(proofSummary(4, 2), "From 4 of your messages, on 2 different days");
});
