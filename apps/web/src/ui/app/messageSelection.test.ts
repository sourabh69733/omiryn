import assert from "node:assert/strict";
import test from "node:test";
import { markDeleted, messageDeletionImpactLines, replyQuoteFor, replyQuoteLabel, toggleSelected } from "./messageSelection";

test("selection toggles and stays in chat order", () => {
  assert.deepEqual(toggleSelected([4], 1), [1, 4]);
  assert.deepEqual(toggleSelected([1, 4], 4), [1]);
});

test("the dialog says what goes, and that the summary is rebuilt", () => {
  assert.deepEqual(messageDeletionImpactLines({ message_count: 2, memories_forgotten: 1, vibe_removed: ["humor"], vibe_weakened: [] }), [
    "Omi will forget 1 thing it learned only from these messages.",
    "Removed from your vibe: Your humor.",
    "Omi rebuilds this chat's summary from what's left.",
  ]);
});

test("deleted messages keep their place but lose their text", () => {
  const after = markDeleted([{ role: "user", content: "hi" }, { role: "assistant", content: "hey" }], [0]);
  assert.deepEqual(after, [{ role: "user", content: "", deleted: true, created_at: undefined }, { role: "assistant", content: "hey" }]);
});

test("a reply quotes a short, clean piece of the message", () => {
  const quote = replyQuoteFor({ role: "assistant", content: "Hi<next_message>there   friend" }, 3);
  assert.deepEqual(quote, { index: 3, role: "assistant", text: "Hi there friend" });
  assert.equal(replyQuoteLabel(quote), "Omi");
  assert.equal(replyQuoteLabel({ index: 3, deleted: true }), "Deleted message");
});

test("deleting a quoted message removes the quote from its reply", () => {
  const after = markDeleted([{ role: "assistant", content: "hey" }, { role: "user", content: "this?", reply_to: { index: 0, role: "assistant", text: "hey" } }], [0]);
  assert.deepEqual(after[1].reply_to, { index: 0, deleted: true });
});
