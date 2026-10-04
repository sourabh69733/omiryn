import assert from "node:assert/strict";
import test from "node:test";
import { isUnread, markSeen, withNewChatsSeen } from "./unread";

test("a chat with messages the user has not seen is unread", () => {
  const seen = { a: 4, b: 6 };
  assert.equal(isUnread({ id: "a", message_count: 6 }, seen, "b"), true);
  assert.equal(isUnread({ id: "b", message_count: 6 }, seen, "a"), false);
});

test("the open chat is never unread", () => {
  assert.equal(isUnread({ id: "a", message_count: 9 }, { a: 4 }, "a"), false);
});

test("chats this browser never listed start as read", () => {
  const seen = withNewChatsSeen({ a: 2 }, [{ id: "a", message_count: 5 }, { id: "b", message_count: 7 }]);
  assert.deepEqual(seen, { a: 2, b: 7 });
  assert.equal(isUnread({ id: "b", message_count: 7 }, seen, null), false);
  assert.equal(isUnread({ id: "a", message_count: 5 }, seen, null), true);
});

test("opening a chat marks what is on screen as seen", () => {
  const seen = { a: 2 };
  assert.deepEqual(markSeen(seen, "a", 5), { a: 5 });
  assert.equal(markSeen(seen, "a", 2), seen);
});
