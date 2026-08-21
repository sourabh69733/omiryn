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

test("keeps the playground survey within a narrow mobile viewport", async () => {
  const css = await readFile(new URL("./themes/playground-v1.css", import.meta.url), "utf8");
  const mobileRules = css.match(/@media \(max-width: 680px\) \{([\s\S]*)\n\}/)?.[1] ?? "";

  assert.match(mobileRules, /\.question-heading h1\s*\{\s*font-size:\s*clamp\(32px, 10vw, 48px\);/);
  assert.match(css, /\.option-row > span:first-child\s*\{[\s\S]*?min-width:\s*0;/);
  assert.match(css, /\.option-row > span:first-child\s*\{[\s\S]*?overflow-wrap:\s*anywhere;/);
  assert.match(mobileRules, /\.concept-screen--playground-v1 \.story-content h2\s*\{\s*font-size:\s*clamp\(30px, 9vw, 42px\);/);
});
