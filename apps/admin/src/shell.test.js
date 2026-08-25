import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("standalone admin shell provides the required auth and app controls", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  for (const id of ["admin-auth", "admin-app", "admin-sign-in", "admin-sign-out"]) {
    assert.ok(html.includes("id=\"" + id + "\""), "expected #" + id + " in standalone admin shell");
  }

  assert.ok(html.includes("/src/main.js"), "expected /src/main.js in standalone admin shell");

  assert.ok(!html.includes("/admin/static/"), "standalone shell must not load backend static assets");
});


test("standalone admin preserves action, route, and auth contracts", async () => {
  const [html, script] = await Promise.all([
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("./main.js", import.meta.url), "utf8"),
  ]);

  assert.match(html, /<div class="admin-actions">\s*<button id="refresh-admin"[\s\S]*?<button[^>]*id="admin-sign-out"/);
  assert.equal((html.match(/id="admin-denied-sign-out"/g) || []).length, 1);
  assert.equal((html.match(/id="admin-sign-out"/g) || []).length, 1);

  for (const href of ["/", "/users", "/requests", "/usage"]) {
    assert.ok(html.includes("href=\"" + href + "\""), "expected standalone route " + href);
  }
  assert.ok(!html.includes("href=\"/admin"), "standalone shell must not link to backend admin routes");
  for (const route of ["users", "requests", "usage"]) {
    assert.ok(script.includes("window.location.pathname === \"/" + route + "\""), "expected route mapper for /" + route);
  }

  for (const path of [
    "/api/admin/overview?limit=50",
    "/api/admin/users/",
    "/api/admin/usage?limit=100",
    "/api/admin/requests?limit=100",
  ]) {
    assert.ok(script.includes("adminFetch(\"" + path) || script.includes("adminFetch(`" + path), "expected adminFetch for " + path);
  }
  assert.doesNotMatch(script, /\bfetch\(/);

  assert.match(script, /if \(response.status === 401\) \{\s*showSignIn\(/);
  assert.match(script, /if \(response.status === 403\) \{\s*showAccessDenied\(/);
  assert.match(script, /adminSignOut\.addEventListener\("click", signOut\);/);
  assert.match(script, /adminDeniedSignOut\.addEventListener\("click", signOut\);/);
});
