import assert from "node:assert/strict";
import test from "node:test";
import { canonicalMemoryEvidenceHref, canonicalMemoryValueText, groupCanonicalMemories, oldMemoryNote, partitionCanonicalMemories } from "./memoryPresentation";

test("groups canonical memories by their actual cognitive kind", () => {
  const sections = groupCanonicalMemories([
    { id: "1", kind: "semantic", key: "home.city", value: "Pune" },
    { id: "2", kind: "episodic", key: "trip.goa", value: "Visited Goa" },
    { id: "3", kind: "relationship", key: "relationship.riya", value: "Trusts Riya" },
    { id: "4", kind: "procedural", key: "conversation.style", value: "One question at a time" }
  ]);

  assert.deepEqual(
    sections.map((section) => [section.id, section.memories.map((memory) => memory.id)]),
    [
      ["semantic", ["1"]],
      ["episodic", ["2"]],
      ["relationship", ["3"]],
      ["procedural", ["4"]]
    ]
  );
});

test("omits empty canonical-memory sections", () => {
  const sections = groupCanonicalMemories([
    { id: "1", kind: "relationship", key: "relationship.riya", value: "Trusts Riya" }
  ]);

  assert.deepEqual(sections.map((section) => section.id), ["relationship"]);
});


test("renders structured memory values as readable text", () => {
  assert.equal(
    canonicalMemoryValueText({ name: "Omiryn", role: "builder" }),
    "name: Omiryn · role: builder"
  );
});


test("links canonical evidence to its exact conversation message", () => {
  assert.equal(
    canonicalMemoryEvidenceHref(
      { conversation_id: "conversation-1", message_index: 4 },
      "https://omiryn.test"
    ),
    "https://omiryn.test/?conversation_id=conversation-1#message-4"
  );
});

test("replaced and ended memories leave the current list", () => {
  const now = new Date("2026-10-06T10:00:00Z");
  const groups = partitionCanonicalMemories(
    [
      { id: "old", kind: "semantic", key: "location", value: "Bangalore", status: "superseded" },
      { id: "new", kind: "semantic", key: "location", value: "Jaipur", status: "active", supersedes_memory_id: "old", created_at: "2026-10-03T10:00:00Z" },
      { id: "trip", kind: "episodic", key: "trip", value: "Wedding in Jaipur", status: "active", valid_until: "2026-10-05T00:00:00Z" },
      { id: "no", kind: "semantic", key: "diet", value: "Vegan", status: "retracted" }
    ],
    now
  );

  assert.deepEqual(groups.active.map((memory) => memory.id), ["new"]);
  assert.deepEqual(groups.old.map((memory) => memory.id), ["old", "trip"]);
  assert.deepEqual(groups.rejected.map((memory) => memory.id), ["no"]);
});

test("an old memory says what replaced it, or when it ended", () => {
  const all = [
    { id: "old", kind: "semantic" as const, key: "location", value: "Bangalore", status: "superseded" },
    { id: "new", kind: "semantic" as const, key: "location", value: "Jaipur", supersedes_memory_id: "old", created_at: "2026-10-03T10:00:00Z" },
    { id: "trip", kind: "episodic" as const, key: "trip", value: "Wedding", valid_until: "2026-10-05T00:00:00Z" }
  ];

  assert.equal(oldMemoryNote(all[0], all), "Replaced by Jaipur on 3 Oct");
  assert.equal(oldMemoryNote(all[2], all), "Ended on 5 Oct");
});
