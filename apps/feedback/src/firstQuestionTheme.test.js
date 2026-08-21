import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { getQuestionScreenClass } from "./firstQuestionTheme.js";

test("gives only the first question the playground treatment", () => {
  assert.equal(getQuestionScreenClass(0), "question-screen question-screen--playground");
  assert.equal(getQuestionScreenClass(1), "question-screen");
});

test("keeps selected playground options light instead of filling them black", async () => {
  const css = await readFile(new URL("./styles.css", import.meta.url), "utf8");
  const selectedRule = css.match(
    /\.question-screen--playground \.option-row\.is-selected\s*\{([^}]*)\}/,
  )?.[1];

  assert.match(selectedRule ?? "", /background:\s*#ffffff;/);
  assert.doesNotMatch(selectedRule ?? "", /background:\s*#111111;/);
});
