import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("mobile chat opens directly and offers navigation instead of a one-chat list", async () => {
  const server = await createServer({ root: "apps/web", configFile: false, esbuild: { jsx: "automatic" }, server: { middlewareMode: true, hmr: false }, appType: "custom" });
  const originalWindow = globalThis.window;
  globalThis.window = {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: true }),
  } as unknown as Window & typeof globalThis;

  try {
    const { MainApp } = await server.ssrLoadModule("/src/ui/app/MainApp.tsx");
    const markup = renderToStaticMarkup(createElement(MainApp));
    assert.match(markup, /aria-label="Open navigation"/);
    assert.doesNotMatch(markup, /omi-contacts-home/);
    assert.match(markup, /class="[^"]*agentic-chat/);
  } finally {
    globalThis.window = originalWindow;
    await server.close();
  }
});
