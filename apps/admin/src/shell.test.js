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
