const maximumBodyBytes = 18_000;

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

function isSubmissionEnvelope(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  if (!/^[0-9a-f-]{36}$/i.test(String(payload.responseId || ""))) return false;
  if (!/^[\w.-]{1,64}$/.test(String(payload.surveyVersion || ""))) return false;
  if (!/^[0-9a-f-]{36}$/i.test(String(payload.clientToken || ""))) return false;
  if (!payload.answers || typeof payload.answers !== "object" || Array.isArray(payload.answers)) {
    return false;
  }
  return typeof payload.website === "string" && payload.website.length <= 200;
}

async function forwardSubmission(request, env) {
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

  if (!isSubmissionEnvelope(payload)) {
    return jsonResponse({ ok: false, code: "invalid_submission" }, 422);
  }
  if (!env.GOOGLE_APPS_SCRIPT_URL || !env.FEEDBACK_SHARED_SECRET) {
    return jsonResponse({ ok: false, code: "submission_not_configured" }, 503);
  }

  // Only the Worker can add this shared secret and trusted Cloudflare source IP.
  // Apps Script validates both the detailed answers and rate limits before writing.
  const upstreamPayload = {
    ...payload,
    internalSecret: env.FEEDBACK_SHARED_SECRET,
    requestIp: request.headers.get("CF-Connecting-IP") || "unknown",
  };

  let upstreamResult;
  try {
    const upstream = await fetch(env.GOOGLE_APPS_SCRIPT_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
      body: JSON.stringify(upstreamPayload),
      redirect: "follow",
    });
    upstreamResult = await upstream.json();
    if (!upstream.ok) throw new Error("upstream_http_error");
  } catch {
    return jsonResponse({ ok: false, code: "storage_unavailable" }, 502);
  }

  if (upstreamResult?.ok !== true) {
    const status = upstreamResult?.code === "rate_limited" ? 429 : 422;
    return jsonResponse({ ok: false, code: upstreamResult?.code || "storage_rejected" }, status);
  }
  return jsonResponse({ ok: true }, upstreamResult.duplicate ? 200 : 201);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/feedback") return forwardSubmission(request, env);
    if (url.pathname.startsWith("/api/")) {
      return jsonResponse({ ok: false, code: "not_found" }, 404);
    }
    return env.ASSETS.fetch(request);
  },
};

export { isSubmissionEnvelope };
