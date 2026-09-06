import assert from "node:assert/strict";
import test from "node:test";
import { cognitionResultLabel } from "./usagePresentation.js";

test("summarizes cognition output counts for the admin usage table", () => {
  assert.equal(
    cognitionResultLabel({
      request_kind: "background_cognition",
      result_summary: {
        memory_operations: 2,
        memories_applied: 2,
        memories_deferred: 0,
        thread_operations_applied: 1
      }
    }),
    "2 memory operations · 2 applied · 1 thread update"
  );
});
