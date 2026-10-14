import assert from "node:assert/strict";
import test from "node:test";
import { TEMPORARY_NAMES, temporaryName } from "./temporaryName";

test("temporaryName picks from the list at both ends", () => {
  assert.equal(temporaryName(() => 0), TEMPORARY_NAMES[0]);
  assert.equal(temporaryName(() => 0.9999), TEMPORARY_NAMES[TEMPORARY_NAMES.length - 1]);
});

test("temporary names stay short enough for the chat header", () => {
  for (const name of TEMPORARY_NAMES) assert.ok(name.length <= 16, name);
});
