import assert from "node:assert/strict";
import test from "node:test";
import * as presentation from "./memoryPresentation";

test("canonical memory cards expose evidence review and usage controls", () => {
  const controls = (presentation as unknown as {
    canonicalMemoryControls?: (evidenceCount: number) => Array<{ id: string; label: string }>;
  }).canonicalMemoryControls;
  assert.equal(typeof controls, "function");
  assert.deepEqual(controls!(1), [
    { id: "evidence", label: "1 evidence" },
    { id: "review", label: "Review accuracy" },
    { id: "usage", label: "Usage" }
  ]);
});
