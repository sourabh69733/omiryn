import assert from "node:assert/strict";
import test from "node:test";
import { uploadDeleteLines } from "./uploadDelete";

test("deleting a read WhatsApp chat lists everything that goes with it", () => {
  assert.deepEqual(
    uploadDeleteLines({
      id: "s1",
      source_type: "whatsapp_chat",
      metadata: { reading: { state: "done", learned: 4 } },
      digest: { summary: "Weekend plans", topics: [{ title: "Goa trip" }] },
    } as never),
    [
      "The chat you shared",
      "What Omi learned about you only from it (4 things)",
      "Its summary and topics",
      "\"What it says about you two\"",
    ],
  );
});

test("an upload that is not read yet lists only what exists", () => {
  assert.deepEqual(uploadDeleteLines({ id: "s2", source_type: "notes" } as never), [
    "The chat you shared",
    "What Omi learned about you only from it",
  ]);
});
