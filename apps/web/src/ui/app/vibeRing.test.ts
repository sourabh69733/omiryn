import assert from "node:assert/strict";
import test from "node:test";
import { blobPath } from "./vibeRing";

test("the same seed always draws the same ring", () => {
  assert.equal(blobPath("user-1", 60, 50), blobPath("user-1", 60, 50));
});

test("different people get different rings", () => {
  assert.notEqual(blobPath("user-1", 60, 50), blobPath("user-2", 60, 50));
});

test("the ring is a closed path within its wobble", () => {
  const path = blobPath("user-1", 60, 50, 0.12, 7);
  assert.match(path, /^M[\d.]+ [\d.]+( C[\d. ]+){7} Z$/);
  const numbers = path.match(/[\d.]+/g)!.map(Number);
  assert.ok(numbers.every((value) => value >= 60 - 50 * 1.3 && value <= 60 + 50 * 1.3));
});
