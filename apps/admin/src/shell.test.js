import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("standalone admin shell provides the required auth and app controls", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  for (const id of ["admin-auth", "admin-app", "admin-sign-in", "admin-sign-out", "admin-denied-sign-out", "refresh-admin", "page"]) {
    assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1, "expected one #" + id);
  }
  assert.ok(html.includes("/src/main.js"), "expected /src/main.js in standalone admin shell");
  assert.ok(!html.includes("/admin/static/"), "standalone shell must not load backend static assets");
  for (const href of ["/", "/users", "/experience", "/growth", "/usage", "/system", "/requests", "/pools"]) {
    assert.ok(html.includes(`href="${href}"`), "expected route link " + href);
  }
  assert.ok(!html.includes('href="/admin'), "standalone shell must not link to backend admin routes");
});

test("admin shell keeps the auth contract and talks to the fast endpoints", async () => {
  const read = (name) => readFile(new URL(name, import.meta.url), "utf8");
  const [main, ...pages] = await Promise.all([
    read("./main.js"),
    read("./pages/dashboard.js"),
    read("./pages/people.js"),
    read("./pages/usage.js"),
    read("./pages/experience.js"),
    read("./pages/growth.js"),
    read("./pages/system.js"),
    read("./pages/requests.js"),
    read("./pages/pools.js"),
  ]);
  const all = [main, ...pages].join("\n");

  assert.match(main, /if \(response.status === 401\) \{\s*showSignIn\(/);
  assert.match(main, /if \(response.status === 403\) \{\s*showAccessDenied\(/);
  assert.match(main, /adminSignOut\.addEventListener\("click", signOut\);/);
  assert.match(main, /adminDeniedSignOut\.addEventListener\("click", signOut\);/);
  assert.doesNotMatch(all, /\bfetch\(/, "pages go through adminFetch only");
  assert.doesNotMatch(all, /\/api\/admin\/overview/, "the slow overview endpoint is no longer used");

  for (const path of ["/api/admin/dashboard", "/api/admin/people", "/api/admin/experience", "/api/admin/growth", "/api/admin/costs", "/api/admin/system", "/api/admin/requests", "/api/admin/pools"]) {
    assert.ok(all.includes(path), "expected a call to " + path);
  }
});
