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


test("separates rejected memories from active memory sections", () => {
  const partition = (presentation as unknown as {
    partitionCanonicalMemories?: (memories: Array<{ id: string; status?: string }>) => {
      active: Array<{ id: string }>;
      rejected: Array<{ id: string }>;
    };
  }).partitionCanonicalMemories;
  assert.equal(typeof partition, "function");
  assert.deepEqual(partition!([
    { id: "active", status: "active" },
    { id: "rejected", status: "retracted" }
  ]), {
    active: [{ id: "active", status: "active" }],
    rejected: [{ id: "rejected", status: "retracted" }]
  });
});

test("maps review state to a quiet card color state", () => {
  const tone = (presentation as unknown as {
    canonicalMemoryCardTone?: (memory: { status?: string; feedback?: { rating?: string } | null }) => string;
  }).canonicalMemoryCardTone;
  assert.equal(typeof tone, "function");
  assert.equal(tone!({ status: "active", feedback: { rating: "agree" } }), "is-approved");
  assert.equal(tone!({ status: "retracted", feedback: { rating: "disagree" } }), "is-rejected");
  assert.equal(tone!({ status: "active", feedback: null }), "");
});


test("builds a canonical review payload from a tag and optional note", () => {
  const buildPayload = (presentation as unknown as {
    canonicalMemoryReviewPayload?: (rating: "agree" | "disagree", reason: string, comment: string) => object;
  }).canonicalMemoryReviewPayload;
  assert.equal(typeof buildPayload, "function");
  assert.deepEqual(buildPayload!("disagree", "outdated", "  I moved recently.  "), {
    rating: "disagree",
    reason: "outdated",
    comment: "I moved recently."
  });
  assert.deepEqual(buildPayload!("agree", "", ""), {
    rating: "agree",
    reason: null,
    comment: null
  });
});
