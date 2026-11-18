import assert from "node:assert/strict";
import test from "node:test";
import { deflateRawSync } from "node:zlib";
import { chatFileText, isZip, MAX_CHAT_CHARS, zippedChatText } from "./chatFile";
import { dropTry, holdTry, isTryPath, takeTry } from "./tryRead";

type Packed = { name: string; data: Uint8Array; deflate?: boolean };

// A small zip written by hand, the way WhatsApp's export is laid out.
function zip(files: Packed[], comment = ""): Blob {
  const parts: Uint8Array[] = [];
  const directory: Uint8Array[] = [];
  let at = 0;
  for (const file of files) {
    const name = new TextEncoder().encode(file.name);
    const body = file.deflate === false ? file.data : new Uint8Array(deflateRawSync(file.data));
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(8, file.deflate === false ? 0 : 8, true);
    local.setUint32(18, body.length, true);
    local.setUint32(22, file.data.length, true);
    local.setUint16(26, name.length, true);
    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014b50, true);
    entry.setUint16(10, file.deflate === false ? 0 : 8, true);
    entry.setUint32(20, body.length, true);
    entry.setUint32(24, file.data.length, true);
    entry.setUint16(28, name.length, true);
    entry.setUint32(42, at, true);
    parts.push(new Uint8Array(local.buffer), name, body);
    directory.push(new Uint8Array(entry.buffer), name);
    at += 30 + name.length + body.length;
  }
  const size = directory.reduce((sum, part) => sum + part.length, 0);
  const note = new TextEncoder().encode(comment);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, size, true);
  end.setUint32(16, at, true);
  end.setUint16(20, note.length, true);
  return new Blob([...parts, ...directory, new Uint8Array(end.buffer), note] as BlobPart[]);
}

const text = (value: string) => new TextEncoder().encode(value);
const CHAT = "[13/09/26, 9:15:02 PM] Riya: hi 😂\n[13/09/26, 9:16:10 PM] Aman: हाँ hello";

test("the chat is read out of an iPhone export zip, past the photos", async () => {
  const photo = new Uint8Array(5000).fill(7);
  const iphone = zip([{ name: "00000012-PHOTO.jpg", data: photo, deflate: false }, { name: "_chat.txt", data: text(CHAT) }]);
  assert.equal(await zippedChatText(iphone), CHAT);
  const stored = zip([{ name: "WhatsApp Chat with Riya.txt", data: text(CHAT), deflate: false }], "made by a phone");
  assert.equal(await zippedChatText(stored), CHAT);
});

test("the chat is chosen over other text files and a Mac's hidden copy", async () => {
  const both = zip([
    { name: "__MACOSX/._chat.txt", data: text("junk") },
    { name: "notes.txt", data: text("my notes") },
    { name: "export/_chat.txt", data: text(CHAT) },
  ]);
  assert.equal(await zippedChatText(both), CHAT);
});

test("a zip with no chat, or a file that is no zip, says so", async () => {
  await assert.rejects(zippedChatText(zip([{ name: "photo.jpg", data: new Uint8Array(10) }])), /no chat in that zip/);
  await assert.rejects(zippedChatText(new Blob(["just some text, not a zip at all"])), /isn't a zip/);
});

test("a picked file gives its text, and a long chat keeps its newest part", async () => {
  assert.equal(isZip({ name: "WhatsApp Chat - Riya.ZIP" }), true);
  assert.equal(isZip({ name: "chat.txt", type: "text/plain" }), false);
  assert.equal(await chatFileText(new File([CHAT], "chat.txt", { type: "text/plain" })), CHAT);
  assert.equal(await chatFileText(new File([zip([{ name: "_chat.txt", data: text(CHAT) }])], "WhatsApp Chat - Riya.zip")), CHAT);
  const long = await chatFileText(new File(["a".repeat(MAX_CHAT_CHARS) + "the end"], "chat.txt"));
  assert.equal(long.length, MAX_CHAT_CHARS);
  assert.ok(long.endsWith("the end"));
});

function memoryStore(room = Infinity) {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (value.length > room) throw new Error("QuotaExceededError");
      items.set(key, value);
    },
    removeItem: (key: string) => void items.delete(key),
  };
}

test("the tried chat is held for sign-in and taken out once", () => {
  const store = memoryStore();
  const held = { text: CHAT, me: "Aman", title: "Riya", kept: "seal.signature" };
  assert.equal(holdTry(held, store), true);
  assert.deepEqual(takeTry(store), held);
  assert.equal(takeTry(store), null);
  assert.equal(store.items.size, 0);
});

test("no room, no storage or a broken note never breaks sign-in", () => {
  const small = memoryStore(10);
  assert.equal(holdTry({ text: CHAT, me: "Aman", title: "Riya", kept: null }, small), false);
  assert.equal(small.items.size, 0);
  assert.equal(holdTry({ text: CHAT, me: "Aman", title: "Riya", kept: null }, null), false);
  assert.equal(takeTry(null), null);
  const broken = memoryStore();
  broken.setItem("omiryn.try_read", "{not json");
  assert.equal(takeTry(broken), null);
  broken.setItem("omiryn.try_read", JSON.stringify({ text: "", me: "Aman" }));
  assert.equal(takeTry(broken), null);
  broken.setItem("omiryn.try_read", JSON.stringify({ text: CHAT, me: "Aman" }));
  assert.deepEqual(takeTry(broken), { text: CHAT, me: "Aman", title: "WhatsApp chat", kept: null });
  holdTry({ text: CHAT, me: "Aman", title: "Riya", kept: null }, broken);
  dropTry(broken);
  assert.equal(takeTry(broken), null);
});

test("the try page has its own address", () => {
  assert.equal(isTryPath("/try"), true);
  assert.equal(isTryPath("/try/"), true);
  assert.equal(isTryPath("/trying"), false);
  assert.equal(isTryPath("/"), false);
});
