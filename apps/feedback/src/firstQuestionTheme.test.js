import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { getScreenTheme } from "./themes.js";

test("uses the playground theme for every survey screen", () => {
  assert.equal(getScreenTheme({ kind: "question", questionIndex: 0 })?.id, "playground-v1");
  assert.equal(getScreenTheme({ kind: "concept" })?.id, "playground-v1");
});

test("keeps selected playground options light instead of filling them black", async () => {
  const css = await readFile(new URL("./themes/playground-v1.css", import.meta.url), "utf8");
  const selectedRule = css.match(
    /\.question-screen--playground-v1 \.option-row\.is-selected\s*\{([^}]*)\}/,
  )?.[1];

  assert.match(selectedRule ?? "", /background:\s*#ffffff;/);
  assert.doesNotMatch(selectedRule ?? "", /background:\s*#111111;/);
});
