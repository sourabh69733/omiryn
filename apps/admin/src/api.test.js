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
