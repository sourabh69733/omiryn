import assert from "node:assert/strict";
import test from "node:test";
import { applyMessageAt, dropLocal, withUserReaction, lastFailedIndex, markBurstFailed, markLocalFailed, mergeServerMessages } from "./messageQueue";
import type { Message } from "./types";

const user = (content: string, extra: Message = {}): Message => ({ role: "user", content, client_id: content, ...extra });
const local = (content: string): Message => user(content, { local: true, delivery_status: "sending" });
const omi = (content: string): Message => ({ role: "assistant", content });
const texts = (messages: Message[]) => messages.map((message) => message.content);

test("a reply landing keeps the bubbles still on their way", () => {
  const current = [user("a", { delivery_status: "sending" }), local("b")];
  assert.deepEqual(texts(mergeServerMessages(current, [user("a"), omi("hi")])), ["a", "hi", "b"]);
});

test("a saved bubble is not shown twice", () => {
  const current = [local("a"), local("b")];
  assert.deepEqual(texts(mergeServerMessages(current, [user("a"), user("b"), omi("hi")])), ["a", "b", "hi"]);
});

test("a response older than what is on screen changes nothing but its bubble", () => {
  const current = [user("a"), omi("hi"), local("b"), local("c")];
  const merged = mergeServerMessages(current, [user("b")]);
  assert.deepEqual(texts(merged), ["a", "hi", "c"]);
});

test("realtime fills the saved part, under the bubbles on their way", () => {
  const current = [user("a"), local("b"), local("c")];
  assert.deepEqual(texts(applyMessageAt(current, 1, user("c"))), ["a", "c", "b"]);
  assert.deepEqual(texts(applyMessageAt(current, 1, omi("hi"))), ["a", "hi", "b", "c"]);
});

test("realtime updates the same message and replaces a moved one", () => {
  const current = [user("a", { delivery_status: "sending", reply_to: { index: 0 } })];
  const read = applyMessageAt(current, 0, { role: "user", content: "a", delivery_status: "read" });
  assert.equal(read[0].delivery_status, "read");
  assert.deepEqual(read[0].reply_to, { index: 0 });
  // A reply was saved above a later message: the reply takes its index and nothing carries over.
  const moved = applyMessageAt([user("a"), user("late")], 1, omi("hi"));
  assert.equal(moved[1].client_id, undefined);
});

test("an event past the end waits for recovery", () => {
  const current = [user("a"), local("b")];
  assert.equal(applyMessageAt(current, 2, omi("hi")), current);
});

test("a rejected bubble goes and the others stay", () => {
  assert.deepEqual(texts(dropLocal([local("a"), local("b")], "a")), ["b"]);
});

test("no answer marks only that bubble", () => {
  const marked = markLocalFailed([local("a"), local("b")], "a");
  assert.deepEqual(marked.map((message) => message.delivery_status), ["failed", "sending"]);
  assert.equal(marked[0].local, true);
});

test("a failed reply marks the saved burst and leaves bubbles on their way", () => {
  const marked = markBurstFailed([user("a", { delivery_status: "sending" }), local("b"), local("c")], "b");
  assert.deepEqual(marked.map((message) => message.delivery_status), ["failed", "failed", "sending"]);
  assert.deepEqual(marked.map((message) => Boolean(message.local)), [false, false, true]);
});

test("only the newest failed message offers Retry", () => {
  const failed = (message: Message) => message.delivery_status === "failed";
  assert.equal(lastFailedIndex([user("a", { delivery_status: "failed" }), user("b", { delivery_status: "failed" }), local("c")], failed), 1);
  assert.equal(lastFailedIndex([local("c")], failed), -1);
});

test("a reaction outlives the message being saved again", () => {
  const current = [user("hmm", { reaction: "👍", delivery_status: "sending" })];
  assert.equal(applyMessageAt(current, 0, user("hmm", { delivery_status: "read" }))[0].reaction, "👍");
  assert.equal(applyMessageAt([user("hmm")], 0, user("hmm", { reaction: "👍" }))[0].reaction, "👍");
});

test("the user reacts only to Omi's messages, and can take it back", () => {
  const current = [user("hmm"), omi("hi")];
  const reacted = withUserReaction(current, 1, "❤️");
  assert.equal(reacted[1].user_reaction, "❤️");
  assert.equal("user_reaction" in withUserReaction(reacted, 1, null)[1], false);
  assert.equal(withUserReaction(current, 0, "❤️"), current);
  assert.equal(withUserReaction(current, 9, "❤️"), current);
});
