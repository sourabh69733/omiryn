import assert from "node:assert/strict";
import test from "node:test";
import { cognitionResultLabel } from "./usagePresentation";

test("summarizes background cognition output counts without exposing its content", () => {
  assert.equal(
    cognitionResultLabel({
      request_kind: "background_cognition",
      result_summary: {
        status: "live_applied",
        memory_operations: 3,
        memories_applied: 2,
        memories_deferred: 1,
        thread_operations_applied: 1
      }
    }),
    "3 memory operations · 2 applied · 1 deferred · 1 thread update"
  );
});

test("returns no cognition label for ordinary chat calls", () => {
  assert.equal(cognitionResultLabel({ request_kind: "chat_reply" }), "");
});
