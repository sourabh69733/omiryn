import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import test from "node:test";

import { acceptSubmission, normalizeSubmission } from "./index.js";

globalThis.crypto = webcrypto;

const validPayload = {
  responseId: "95a3e072-6028-454c-a70d-1a559c91ec72",
  surveyVersion: "2026-08-19-v4",
  clientToken: "cfbc49c3-358a-40be-af36-a6b141d0e1f9",
  website: "",
  answers: {
    dating_openness: ["Open to it"],
    compatibility_challenges: ["Meeting the right people"],
    compatibility_signals: ["Shared values"],
    ai_disclosure_comfort: ["Somewhat comfortable"],
    depth_vs_speed: ["Somewhere in between"],
    intro_time_willingness: ["10-15 minutes"],
    concept_concerns: ["Privacy and personal data"],
    must_get_right: ["Privacy"],
  },
};

function requestFor(payload = validPayload) {
  return new Request("https://feedback.omiryn.com/api/feedback", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "CF-Connecting-IP": "203.0.113.10",
    },
    body: JSON.stringify(payload),
  });
}

function database({ recentCount = 0, changes = 1 } = {}) {
  return {
    prepare(sql) {
      return {
        bind(...values) {
          if (sql.includes("SELECT COUNT")) {
            return { first: async () => ({ count: recentCount }) };
          }
          assert.equal(sql.includes("INSERT OR IGNORE"), true);
          assert.equal(values.includes("203.0.113.10"), false, "raw IP must not reach D1");
          assert.equal(values.includes(validPayload.clientToken), false, "raw client token must not reach D1");
          return { run: async () => ({ meta: { changes } }) };
        },
      };
    },
  };
}

function environment(databaseOptions) {
  return {
    FEEDBACK_DB: database(databaseOptions),
    FEEDBACK_SHARED_SECRET: "test-secret-with-at-least-32-characters",
  };
}

test("stores a valid submission before returning success", async () => {
  const response = await acceptSubmission(requestFor(), environment());
  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), { ok: true });
});

test("treats an idempotent insert as an existing submission", async () => {
  const response = await acceptSubmission(requestFor(), environment({ changes: 0 }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test("rejects a source over the hourly limit", async () => {
  const response = await acceptSubmission(
    requestFor(),
    environment({ recentCount: 100 }),
  );
  assert.equal(response.status, 429);
  assert.deepEqual(await response.json(), { ok: false, code: "rate_limited" });
});

test("rejects answers outside the server allowlist", async () => {
  const payload = structuredClone(validPayload);
  payload.answers.dating_openness = ["A made-up answer"];
  const response = await acceptSubmission(requestFor(payload), environment());
  assert.equal(response.status, 422);
  assert.deepEqual(await response.json(), { ok: false, code: "invalid_submission" });
});

test("supports unrestricted multi-select while keeping none options exclusive", () => {
  const payload = structuredClone(validPayload);
  payload.answers.compatibility_challenges = [
    "Meeting the right people",
    "Understanding real intentions",
    "Knowing if values and personalities match",
    "Starting a meaningful conversation",
    "Trust and personal safety",
    "Too many low-quality or repetitive matches",
    "Social pressure or awkwardness",
    "Limited time or opportunities",
  ];
  assert.ok(normalizeSubmission(payload));

  payload.answers.compatibility_challenges.push("I don't think it is particularly difficult");
  assert.equal(normalizeSubmission(payload), null);
});

test("accepts one bounded custom option and normalizes its whitespace", () => {
  const payload = structuredClone(validPayload);
  payload.answers.compatibility_challenges.push("Other:   Distance between cities  ");

  const submission = normalizeSubmission(payload);
  assert.deepEqual(submission.answers.compatibility_challenges, [
    "Meeting the right people",
    "Other: Distance between cities",
  ]);

  payload.answers.compatibility_challenges.push("Other: A second custom answer");
  assert.equal(normalizeSubmission(payload), null);

  payload.answers.compatibility_challenges = [`Other: ${"x".repeat(121)}`];
  assert.equal(normalizeSubmission(payload), null);
});

test("fails closed when D1 is not bound", async () => {
  const response = await acceptSubmission(
    requestFor(),
    { FEEDBACK_SHARED_SECRET: "test-secret-with-at-least-32-characters" },
  );
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { ok: false, code: "submission_not_configured" });
});
