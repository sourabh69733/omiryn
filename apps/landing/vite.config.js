import { defineConfig } from "vite";
import path from "node:path";

const landingRoot = path.resolve("apps/landing");
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;
const appDevOrigin = process.env.VITE_APP_DEV_ORIGIN ?? "http://127.0.0.1:5173";
const pages = [
  "landing",
  "about",
  "how-it-works",
  "safety",
  "ai-disclosure",
  "privacy",
  "terms",
  "contact"
];

function landingRoutesPlugin() {
  const publicPages = new Set(pages.filter((page) => page !== "landing"));
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
        if (pathname === "/") request.url = "/landing.html";
        else if (publicPages.has(pathname.slice(1))) request.url = `${pathname}.html`;
        next();
      });
    }
  };
}

export default defineConfig({
  root: landingRoot,
  publicDir: "public",
  plugins: [landingRoutesPlugin()],
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
