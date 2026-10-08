import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("the profile privacy URL opens the privacy explanation", async () => {
  const server = await createServer({ root: "apps/web", configFile: false, esbuild: { jsx: "automatic" }, server: { middlewareMode: true, hmr: false }, appType: "custom" });
  const originalWindow = globalThis.window;
  globalThis.window = {
    location: { pathname: "/profile/privacy", search: "" },
    matchMedia: () => ({ matches: false }),
  } as unknown as Window & typeof globalThis;

  try {
    const { MainApp } = await server.ssrLoadModule("/src/ui/app/MainApp.tsx");
    const markup = renderToStaticMarkup(createElement(MainApp));
    assert.match(markup, /Your privacy with Omi/);
    assert.match(markup, /How Omi uses your messages/);
    assert.doesNotMatch(markup, /Loading your profile/);
  } finally {
    globalThis.window = originalWindow;
    await server.close();
  }
});
