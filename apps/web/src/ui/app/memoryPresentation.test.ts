import assert from "node:assert/strict";
import test from "node:test";
import { canonicalMemoryEvidenceHref, canonicalMemoryValueText, groupCanonicalMemories } from "./memoryPresentation";

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
