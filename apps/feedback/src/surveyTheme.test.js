import assert from "node:assert/strict";
import test from "node:test";

import { toggleAnswer } from "./answerSelection.js";
import { getScreenTheme } from "./themes.js";

test("keeps earlier multiple-choice answers when another option is selected", () => {
  assert.deepEqual(
    toggleAnswer({
      type: "multiple",
      selected: ["Meeting the right people"],
      option: "I don't think it is particularly difficult",
    }),
    ["Meeting the right people", "I don't think it is particularly difficult"],
  );
});

test("assigns the versioned playground theme to questions and information screens", () => {
  assert.deepEqual(getScreenTheme({ kind: "question", questionIndex: 0 }), {
    id: "playground-v1",
    mainClassName: "feedback-main--playground-v1",
    appClassName: "feedback-app--playground-v1",
    screenClassNames: {
      welcome: "welcome-screen--playground-v1",
      question: "question-screen--playground-v1",
      concept: "concept-screen--playground-v1",
      completion: "completion-screen--playground-v1",
    },
  });
  assert.equal(getScreenTheme({ kind: "concept" })?.id, "playground-v1");
  assert.equal(getScreenTheme({ kind: "welcome" })?.id, "playground-v1");
});
