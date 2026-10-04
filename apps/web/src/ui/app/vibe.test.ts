import assert from "node:assert/strict";
import test from "node:test";
import { confidenceLevel, deletionImpactLines, evidenceChatPath, milestoneFromEvent, proofSummary, strengthLabel, vibeStepNote } from "./vibe";

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
  assert.equal(strengthLabel("mentioned"), "Still learning");
  assert.equal(proofSummary(1, 1), "From 1 of your messages");
  assert.equal(proofSummary(4, 2), "From 4 of your messages, on 2 different days");
});

test("the chip color deepens with the proof", () => {
  assert.equal(confidenceLevel(1, 1), 1);
  assert.equal(confidenceLevel(3, 1), 2);
  assert.equal(confidenceLevel(2, 2), 3);
  assert.equal(confidenceLevel(5, 3), 4);
});

test("the delete dialog says what goes with the chat", () => {
  assert.deepEqual(deletionImpactLines({ memories_forgotten: 0, vibe_removed: [], vibe_weakened: [] }), []);
  assert.deepEqual(deletionImpactLines({ memories_forgotten: 3, vibe_removed: ["humor"], vibe_weakened: ["interests"] }), [
    "Omi will forget 3 things it learned only from this chat.",
    "Removed from your vibe: Your humor.",
    "Less proof for: What you love.",
  ]);
  assert.deepEqual(deletionImpactLines({ memories_forgotten: 0, vibe_removed: [], vibe_weakened: [], topics_dropped: ["Guitar", "Exams"] }), [
    "Omi won't bring these up again: Guitar, Exams.",
  ]);
});
