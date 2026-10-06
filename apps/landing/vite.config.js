import { defineConfig } from "vite";
import fs from "node:fs";
import path from "node:path";

const landingRoot = path.resolve("apps/landing");
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;
const appDevOrigin = process.env.VITE_APP_DEV_ORIGIN ?? "http://127.0.0.1:5173";
const pages = [
  "index",
  "about",
  "how-it-works",
  "safety",
  "ai-disclosure",
  "privacy",
  "terms",
  "contact"
];

function landingRoutesPlugin() {
  const publicPages = new Set(pages.filter((page) => page !== "index"));
  return {
    name: "omiryn-landing-routes",
    transformIndexHtml: {
      order: "pre",
      handler(html, context) {
        if (!context.server) return html;
        return html.replace("data-app-origin=", `data-local-app-origin="${appDevOrigin}" data-app-origin=`);
      }
    },
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        const pathname = new URL(request.url || "/", "http://127.0.0.1").pathname;
        if (pathname === "/") request.url = "/index.html";
        else if (publicPages.has(pathname.slice(1))) request.url = `${pathname}.html`;
        next();
      });
    }
  };
}

// Build only: inline our small stylesheets and load Google Fonts without
// blocking first paint. Both were render-blocking on mobile Lighthouse.
function landingCriticalCssPlugin() {
  return {
    name: "omiryn-landing-critical-css",
    apply: "build",
    transformIndexHtml(html) {
      return html
        .replace(/<link rel="stylesheet" href="\/static\/([\w-]+\.css)(?:\?[^"]*)?">/g, (_tag, file) => {
          const css = fs.readFileSync(path.join(landingRoot, "public/static", file), "utf8");
          return `<style>${css}</style>`;
        })
        .replace(/<link href="(https:\/\/fonts\.googleapis\.com\/css2[^"]*)" rel="stylesheet">/g, (_tag, href) =>
          `<link rel="preload" as="style" href="${href}">` +
          `<link rel="stylesheet" href="${href}" media="print" onload="this.media='all'">` +
          `<noscript><link rel="stylesheet" href="${href}"></noscript>`
        );
    }
  };
}

export default defineConfig({
  root: landingRoot,
  publicDir: "public",
  plugins: [landingRoutesPlugin(), landingCriticalCssPlugin()],
  // Own dep cache: the web app's dev server shares node_modules/.vite and would
  // otherwise invalidate our pre-bundled GSAP ("504 Outdated Optimize Dep").
  cacheDir: path.resolve("node_modules/.vite-landing"),
  // Pre-bundle GSAP up front so the dev server never serves a stale copy.
  optimizeDeps: {
    include: ["gsap", "gsap/ScrollTrigger"]
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: Object.fromEntries(pages.map((page) => [page, path.join(landingRoot, `${page}.html`)]))
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": apiProxyTarget
    }
  }
});
