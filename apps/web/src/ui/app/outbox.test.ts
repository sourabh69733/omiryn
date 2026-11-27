import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { addToOutbox, clearSavedWriting, loadDraft, loadOutbox, removeFromOutbox, restoreOutbox, saveDraft } from "./outbox";
import type { Message } from "./types";

class MemoryStorage {
  private data = new Map<string, string>();
  get length() { return this.data.size; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}

beforeEach(() => {
  (globalThis as { window?: unknown }).window = { localStorage: new MemoryStorage() };
});

const item = (id: string, content = `text ${id}`) => ({ client_id: id, content, created_at: "2026-11-27T10:00:00Z" });

test("a sent message stays until the server has it, and comes back after a refresh with Retry", () => {
  addToOutbox("c1", item("a", "kal interview hai"));
  addToOutbox("c1", item("b"));
  const saved: Message[] = [{ role: "user", content: "earlier", client_id: "old" }, { role: "assistant", content: "hi" }];
  const shown = restoreOutbox("c1", saved);
  assert.equal(shown.length, 4);
  assert.deepEqual(shown.slice(2).map((m) => [m.content, m.delivery_status, m.local]), [["kal interview hai", "failed", true], ["text b", "failed", true]]);
});

test("what the server already saved leaves the outbox and is not shown twice", () => {
  addToOutbox("c1", item("a"));
  addToOutbox("c1", item("b"));
  const shown = restoreOutbox("c1", [{ role: "user", content: "text a", client_id: "a" }]);
  assert.deepEqual(shown.map((m) => m.client_id), ["a", "b"]);
  assert.deepEqual(loadOutbox("c1").map((i) => i.client_id), ["b"]);
});

test("a bubble already on screen is not added again, and a retry does not duplicate", () => {
  addToOutbox("c1", item("a"));
  addToOutbox("c1", item("a"));
  assert.equal(loadOutbox("c1").length, 1);
  const onScreen: Message[] = [{ role: "user", content: "text a", client_id: "a", local: true, delivery_status: "sending" }];
  assert.equal(restoreOutbox("c1", onScreen).length, 1);
  removeFromOutbox("c1", "a");
  assert.deepEqual(loadOutbox("c1"), []);
});

test("drafts are per chat, an empty one is removed, and sign out clears everything written", () => {
  saveDraft("c1", "half a thought");
  saveDraft("c2", "   ");
  assert.equal(loadDraft("c1"), "half a thought");
  assert.equal(loadDraft("c2"), "");
  addToOutbox("c2", item("x"));
  clearSavedWriting();
  assert.equal(loadDraft("c1"), "");
  assert.deepEqual(loadOutbox("c2"), []);
});

test("blocked storage keeps nothing and never breaks the chat", () => {
  (globalThis as { window?: unknown }).window = { get localStorage() { throw new Error("blocked"); } };
  addToOutbox("c1", item("a"));
  saveDraft("c1", "x");
  assert.deepEqual(loadOutbox("c1"), []);
  assert.equal(loadDraft("c1"), "");
  assert.deepEqual(restoreOutbox("c1", []), []);
  clearSavedWriting();
});
