import assert from "node:assert/strict";
import test from "node:test";

import { buildApiUrl, createAdminFetch } from "./api.js";

test("builds backend URLs without duplicate slashes", () => {
  assert.equal(buildApiUrl("https://api.omiryn.com/", "/api/admin/overview"),
    "https://api.omiryn.com/api/admin/overview");
});

test("adds the current bearer token to admin requests", async () => {
  let received;
  const adminFetch = createAdminFetch({
    apiBaseUrl: "https://api.omiryn.com",
    getAccessToken: async () => "admin-token",
    fetchImpl: async (url, init) => {
      received = { url, headers: new Headers(init.headers) };
      return new Response("{}", { status: 200 });
    },
    onUnauthorized: async () => {},
  });
  await adminFetch("/api/admin/overview");
  assert.equal(received.headers.get("Authorization"), "Bearer admin-token");
});

test("rejects absolute URLs before retrieving a bearer token", async () => {
  let tokenReads = 0;
  const adminFetch = createAdminFetch({
    apiBaseUrl: "https://api.omiryn.com",
    getAccessToken: async () => {
      tokenReads += 1;
      return "admin-token";
    },
    fetchImpl: async () => new Response("{}", { status: 200 }),
  });

  await assert.rejects(() => adminFetch("https://attacker.example/api/admin/overview"),
    /backend-relative/);
  assert.equal(tokenReads, 0);
});

test("invokes onUnauthorized exactly once for a 401 response", async () => {
  let unauthorizedCalls = 0;
  const adminFetch = createAdminFetch({
    apiBaseUrl: "https://api.omiryn.com",
    getAccessToken: async () => "admin-token",
    fetchImpl: async () => new Response("{}", { status: 401 }),
    onUnauthorized: async () => {
      unauthorizedCalls += 1;
    },
  });

  await adminFetch("/api/admin/overview");
  assert.equal(unauthorizedCalls, 1);
});

test("does not invoke onUnauthorized for a 403 response", async () => {
  let unauthorizedCalls = 0;
  const adminFetch = createAdminFetch({
    apiBaseUrl: "https://api.omiryn.com",
    getAccessToken: async () => "admin-token",
    fetchImpl: async () => new Response("{}", { status: 403 }),
    onUnauthorized: async () => {
      unauthorizedCalls += 1;
    },
  });

  await adminFetch("/api/admin/overview");
  assert.equal(unauthorizedCalls, 0);
});
