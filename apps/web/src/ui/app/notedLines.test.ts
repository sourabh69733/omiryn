import assert from "node:assert/strict";
import test from "node:test";
import { notedLinesByMessage } from "./notedLines";
import type { VibeArea } from "./vibe";

const area = (id: string, text: string | null, proof: Array<[string, number]>, isPrivate = false): VibeArea => ({
  id, stage: "basics", private: isPrivate, text, strength: text ? "mentioned" : null, evidence_count: proof.length, evidence_days: 1,
  evidence: proof.map(([conversation_id, message_index]) => ({ quote: "q", conversation_id, message_index, sent_at: null })),
});

const chat = [
  { role: "assistant", content: "hey" },
  { role: "user", content: "my teammate ghosted us" },
  { role: "assistant", content: "ugh" },
  { role: "assistant", content: "flakes are the worst" },
  { role: "user", content: "puns are my thing" },
];

test("a line shows after Omi's whole reply to its newest proof", () => {
  const placed = notedLinesByMessage([area("friend_wish", "Wants friends who show up.", [["c1", 1]])], "c1", chat);
  assert.deepEqual([...placed.keys()], [3]);
  assert.equal(placed.get(3)?.[0].text, "Wants friends who show up.");
});

test("before Omi replies, the line sits under the message itself", () => {
  const placed = notedLinesByMessage([area("humor", "Loves puns.", [["c1", 4]])], "c1", chat);
  assert.deepEqual([...placed.keys()], [4]);
});

test("only the newest proof counts, and only in this chat", () => {
  const placed = notedLinesByMessage(
    [area("humor", "Loves puns.", [["c2", 9], ["c1", 1]]), area("interests", null, [["c1", 1]]), area("values", "Honest.", [["c1", 1]], true)],
    "c1",
    chat,
  );
  assert.deepEqual([...placed.entries()].map(([at, lines]) => [at, lines.map((line) => line.areaId)]), [[3, ["values"]]]);
  assert.equal(placed.get(3)?.[0].private, true);
});

test("proof outside the messages on screen is ignored", () => {
  assert.equal(notedLinesByMessage([area("humor", "Loves puns.", [["c1", 12]])], "c1", chat).size, 0);
});
