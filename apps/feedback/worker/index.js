const maximumBodyBytes = 18_000;
const maximumOtherAnswerLength = 120;
const otherAnswerPrefix = "Other: ";
// Keep obvious floods bounded without blocking classrooms or campus Wi-Fi,
// where many legitimate respondents can share one public IP address.
const maximumSubmissionsPerIpHour = 100;

// This server-side allowlist is intentionally independent of the React form.
// A caller can bypass the UI, so D1 must only receive known survey answers.
const questionRules = {
  dating_openness: {
    min: 1,
    max: 1,
    options: [
      "Actively looking",
      "Open to it",
      "Not looking right now",
      "Prefer not to say",
    ],
  },
  compatibility_challenges: {
    min: 1,
    max: 10,
    allowOther: true,
    exclusiveOptions: ["I don't think it is particularly difficult"],
    options: [
      "Meeting the right people",
      "Understanding real intentions",
      "Knowing if values and personalities match",
      "Starting a meaningful conversation",
      "Trust and personal safety",
      "Too many low-quality or repetitive matches",
      "Social pressure or awkwardness",
      "Limited time or opportunities",
      "I don't think it is particularly difficult",
    ],
  },
  compatibility_signals: {
    min: 1,
    max: 9,
    allowOther: true,
    options: [
      "Shared values",
      "Similar relationship intentions",
      "Personality",
      "Communication style",
      "Lifestyle",
      "Interests",
      "Family or cultural background",
      "Physical attraction",
    ],
  },
  ai_disclosure_comfort: {
    min: 1,
    max: 1,
    options: [
      "Very comfortable",
      "Somewhat comfortable",
      "Depends on what's asked",
      "Not very comfortable",
      "Not comfortable at all",
    ],
  },
  depth_vs_speed: {
    min: 1,
    max: 1,
    options: [
      "Match me quickly, even if less accurate",
      "Take your time, I want it to really understand me",
      "Somewhere in between",
      "Not sure",
    ],
  },
  intro_time_willingness: {
    min: 1,
    max: 1,
    options: [
      "Under 10 minutes",
      "10-15 minutes",
      "20-30 minutes",
      "More than 60 minutes",
      "I would not want to do this",
    ],
  },
  concept_concerns: {
    min: 1,
    max: 9,
    allowOther: true,
    exclusiveOptions: ["Nothing concerns me yet"],
    options: [
      "Privacy and personal data",
      "AI understanding someone incorrectly",
      "Compatibility cannot be predicted",
      "Losing spontaneity or human judgement",
      "Fake profiles and safety",
      "Not enough relevant people",
      "The process taking too much effort",
      "Nothing concerns me yet",
    ],
  },
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function isToken(value, maximumLength) {
  return typeof value === "string"
    && value.length > 0
    && value.length <= maximumLength
    && /^[A-Za-z0-9_.-]+$/.test(value);
}

function normalizeChoice(value, rule) {
  if (typeof value !== "string") return null;
  if (rule.options.includes(value)) return value;
  if (!rule.allowOther || !value.startsWith(otherAnswerPrefix)) return null;

  const customText = value.slice(otherAnswerPrefix.length).trim();
  if (!customText || customText.length > maximumOtherAnswerLength) return null;
  return `${otherAnswerPrefix}${customText}`;
}

function normalizeSubmission(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (!isToken(payload.responseId, 36) || !isToken(payload.clientToken, 36)) return null;
  if (!isToken(payload.surveyVersion, 64)) return null;
  if (typeof payload.website !== "string" || payload.website.length > 200) return null;
  if (!payload.answers || typeof payload.answers !== "object" || Array.isArray(payload.answers)) {
    return null;
  }

  const answers = {};
  for (const [questionId, rule] of Object.entries(questionRules)) {
    const values = payload.answers[questionId];
    if (!Array.isArray(values) || values.length < rule.min || values.length > rule.max) return null;
    // Custom choices are canonicalized before uniqueness and exclusivity checks.
    const normalizedValues = values.map((value) => normalizeChoice(value, rule));
    if (normalizedValues.some((value) => value === null)) return null;
    const uniqueValues = [...new Set(normalizedValues)];
    const customAnswerCount = uniqueValues.filter(
      (value) => value.startsWith(otherAnswerPrefix),
    ).length;
    if (
      uniqueValues.length !== values.length
      || customAnswerCount > 1
      || (
        uniqueValues.length > 1
        && rule.exclusiveOptions?.some((option) => uniqueValues.includes(option))
      )
    ) {
      return null;
    }
    answers[questionId] = uniqueValues;
  }

  const openAnswer = payload.answers.must_get_right ?? [];
  if (!Array.isArray(openAnswer) || openAnswer.length > 1) return null;
  if (openAnswer.length === 1 && typeof openAnswer[0] !== "string") return null;
  const mustGetRight = String(openAnswer[0] || "").trim();
  if (mustGetRight.length > 250) return null;

  return {
    responseId: payload.responseId,
    surveyVersion: payload.surveyVersion,
    clientToken: payload.clientToken,
    website: payload.website,
    answers,
    mustGetRight,
  };
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function storeSubmission(submission, request, env) {
  const sourceIp = request.headers.get("CF-Connecting-IP") || "unknown";
  const sourceHash = await sha256(`source:${sourceIp}:${env.FEEDBACK_SHARED_SECRET}`);
  const clientHash = await sha256(
    `client:${submission.surveyVersion}:${submission.clientToken}:${env.FEEDBACK_SHARED_SECRET}`,
  );

  // The composite index makes this abuse check bounded even as responses grow.
  // Raw IP addresses and browser tokens are never persisted.
  const recent = await env.FEEDBACK_DB.prepare(`
    SELECT COUNT(*) AS count
    FROM feedback_submissions
    WHERE source_hash = ? AND received_at >= datetime('now', '-1 hour')
  `).bind(sourceHash).first();
  if (Number(recent?.count || 0) >= maximumSubmissionsPerIpHour) {
    return { rateLimited: true };
  }

  const result = await env.FEEDBACK_DB.prepare(`
    INSERT OR IGNORE INTO feedback_submissions (
      response_id,
      survey_version,
      client_token_hash,
      source_hash,
      dating_openness,
      compatibility_challenges,
      compatibility_signals,
      ai_disclosure_comfort,
      depth_vs_speed,
      intro_time_willingness,
      concept_concerns,
      must_get_right
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    submission.responseId,
    submission.surveyVersion,
    clientHash,
    sourceHash,
    submission.answers.dating_openness[0],
    JSON.stringify(submission.answers.compatibility_challenges),
    JSON.stringify(submission.answers.compatibility_signals),
    submission.answers.ai_disclosure_comfort[0],
    submission.answers.depth_vs_speed[0],
    submission.answers.intro_time_willingness[0],
    JSON.stringify(submission.answers.concept_concerns),
    submission.mustGetRight,
  ).run();

  return { duplicate: Number(result.meta?.changes || 0) === 0 };
}

async function acceptSubmission(request, env) {
  if (request.method !== "POST") return jsonResponse({ ok: false, code: "method_not_allowed" }, 405);

  const declaredLength = Number(request.headers.get("Content-Length") || 0);
  if (declaredLength > maximumBodyBytes) {
    return jsonResponse({ ok: false, code: "payload_too_large" }, 413);
  }

  let payload;
  try {
    const body = await request.text();
    if (new TextEncoder().encode(body).byteLength > maximumBodyBytes) {
      return jsonResponse({ ok: false, code: "payload_too_large" }, 413);
    }
    payload = JSON.parse(body);
  } catch {
    return jsonResponse({ ok: false, code: "invalid_json" }, 400);
  }

  const submission = normalizeSubmission(payload);
  if (!submission) return jsonResponse({ ok: false, code: "invalid_submission" }, 422);
  if (submission.website) return jsonResponse({ ok: true }, 201);
  if (!env.FEEDBACK_DB || !env.FEEDBACK_SHARED_SECRET) {
    return jsonResponse({ ok: false, code: "submission_not_configured" }, 503);
  }

  let stored;
  try {
    stored = await storeSubmission(submission, request, env);
  } catch (error) {
    console.error("Feedback D1 write failed", error);
    return jsonResponse({ ok: false, code: "storage_unavailable" }, 503);
  }

  if (stored.rateLimited) return jsonResponse({ ok: false, code: "rate_limited" }, 429);
  return jsonResponse({ ok: true }, stored.duplicate ? 200 : 201);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/feedback") return acceptSubmission(request, env);
    if (url.pathname.startsWith("/api/")) {
      return jsonResponse({ ok: false, code: "not_found" }, 404);
    }
    return env.ASSETS.fetch(request);
  },
};

export { acceptSubmission, normalizeSubmission };
