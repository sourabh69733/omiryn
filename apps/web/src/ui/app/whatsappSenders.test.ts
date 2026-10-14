import assert from "node:assert/strict";
import test from "node:test";
import { chatSenders, chatTitle } from "./whatsappSenders";

const ANDROID = `13/09/2026, 9:15 pm - Riya: hey did you see the match
13/09/2026, 9:16 pm - Sourabh: yes!! kohli was insane
continued line without a header
13/09/2026, 9:17 pm - Sourabh: moving to pune btw
13/09/2026, 9:18 pm - Messages and calls are end-to-end encrypted.`;

test("senders are found in Android and iPhone exports, most messages first", () => {
  assert.deepEqual(chatSenders(ANDROID), [{ name: "Sourabh", count: 2 }, { name: "Riya", count: 1 }]);
  const iphone = "[13/09/26, 9:15:02 PM] Riya: hi\n‎[13/09/26, 9:16:10 PM] Me: hello";
  assert.deepEqual(chatSenders(iphone).map((sender) => sender.name), ["Riya", "Me"]);
});

test("plain text has no senders", () => {
  assert.deepEqual(chatSenders("I live in Pune and love long drives."), []);
});

test("the title comes from the file name, else the other person", () => {
  const senders = chatSenders(ANDROID);
  assert.equal(chatTitle("WhatsApp Chat with Riya.txt", senders, "Sourabh"), "Riya");
  assert.equal(chatTitle("_chat.txt", senders, "Sourabh"), "Riya");
});
