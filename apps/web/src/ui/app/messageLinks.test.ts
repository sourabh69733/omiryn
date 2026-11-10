import assert from "node:assert/strict";
import test from "node:test";
import { pageButton, splitLinks } from "./messageLinks";

test("a link in a bubble becomes its own part, without the full stop after it", () => {
  assert.deepEqual(splitLinks("Try this: https://maps.google.com/?q=cafe. Nice spot"), [
    { text: "Try this: " },
    { text: "https://maps.google.com/?q=cafe", href: "https://maps.google.com/?q=cafe" },
    { text: ". Nice spot" },
  ]);
});

test("text without links stays one part, and only http links count", () => {
  assert.deepEqual(splitLinks("no links here"), [{ text: "no links here" }]);
  assert.deepEqual(splitLinks("javascript:alert(1) and ftp://x"), [{ text: "javascript:alert(1) and ftp://x" }]);
});

test("two links in one bubble", () => {
  const parts = splitLinks("https://a.com and https://b.com/x");
  assert.deepEqual(parts.filter((part) => part.href).map((part) => part.href), ["https://a.com", "https://b.com/x"]);
});

test("only app pages get a button", () => {
  assert.deepEqual(pageButton("privacy"), { page: "privacy", label: "Open Privacy" });
  assert.equal(pageButton("contact"), null);
  assert.equal(pageButton("settings"), null);
  assert.equal(pageButton(undefined), null);
});
