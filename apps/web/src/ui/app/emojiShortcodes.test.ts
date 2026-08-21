import assert from "node:assert/strict";
import test from "node:test";
import { findEmojiQuery, loadEmojiRecords, replaceEmojiQuery, searchEmojiSuggestions } from "./emojiShortcodes";

const emojis = [
  { group: 0, hexcode: "1F602", label: "face with tears of joy", tags: ["funny", "joy", "laugh", "lol"], unicode: "😂" },
  { group: 0, hexcode: "1F923", label: "rolling on the floor laughing", tags: ["laugh", "rofl"], unicode: "🤣" },
  { group: 0, hexcode: "1F60D", label: "smiling face with heart-eyes", tags: ["love", "crush"], unicode: "😍" }
];

test("finds an emoji query at the cursor after whitespace", () => {
  assert.deepEqual(findEmojiQuery("That was :lau", 13), { start: 9, end: 13, query: "lau" });
});

test("does not treat URL and time colons as emoji queries", () => {
  assert.equal(findEmojiQuery("https://omiryn.com", 7), null);
  assert.equal(findEmojiQuery("Meet at 12:30", 13), null);
});

test("ranks exact tag matches before partial label matches", () => {
  assert.deepEqual(searchEmojiSuggestions("laugh", emojis, 2).map((item) => item.unicode), ["😂", "🤣"]);
});

test("replaces only the active shortcode and returns the new cursor", () => {
  assert.deepEqual(
    replaceEmojiQuery("That was :lau today", { start: 9, end: 13, query: "lau" }, "😂"),
    { value: "That was 😂 today", cursor: 11 }
  );
});

test("loads the real emoji catalog and finds laugh suggestions", async () => {
  const records = await loadEmojiRecords();
  const suggestions = searchEmojiSuggestions("laugh", records);
  assert.ok(suggestions.length > 0);
  assert.ok(suggestions.some((item) => item.unicode === "😂"));
});
