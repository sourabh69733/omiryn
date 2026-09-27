import assert from "node:assert/strict";
import test from "node:test";
import { isFailedMessage } from "./messageDelivery";

const now = Date.parse("2026-09-27T10:00:00+00:00");

test("a failed reply shows Retry", () => {
  assert.equal(isFailedMessage({ role: "user", content: "hi", delivery_status: "failed" }, now), true);
  assert.equal(isFailedMessage({ role: "user", content: "hi", delivery_status: "read" }, now), false);
  assert.equal(isFailedMessage({ role: "assistant", content: "hey", delivery_status: "failed" }, now), false);
});

test("a reply still sending after two minutes counts as failed", () => {
  const recent = { role: "user", content: "hi", delivery_status: "sending", created_at: "2026-09-27T09:59:30+00:00" };
  const stale = { ...recent, created_at: "2026-09-27T09:57:00+00:00" };
  assert.equal(isFailedMessage(recent, now), false);
  assert.equal(isFailedMessage(stale, now), true);
});
