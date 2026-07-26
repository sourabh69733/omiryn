import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;
const publicDir = path.resolve("frontend/public");

function serveFile(response, filePath, contentType) {
  if (!fs.existsSync(filePath)) {
    response.statusCode = 404;
    response.end("Not found");
    return;
  }
  response.setHeader("Content-Type", contentType);
  response.setHeader("Cache-Control", "no-store");
  response.end(fs.readFileSync(filePath));
}

function landingDevPlugin() {
  const publicPages = new Set(["about", "how-it-works", "safety", "ai-disclosure", "privacy", "terms", "contact"]);
  return {
    name: "omiryn-landing-dev",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = new URL(request.url || "/", "http://127.0.0.1").pathname;
        if (pathname === "/") {
          serveFile(response, path.join(publicDir, "landing.html"), "text/html; charset=utf-8");
          return;
        }
        const pageName = pathname.slice(1);
        if (publicPages.has(pageName)) {
          serveFile(response, path.join(publicDir, `${pageName}.html`), "text/html; charset=utf-8");
          return;
        }
        if (pathname === "/static/landing.css") {
          serveFile(response, path.join(publicDir, "landing.css"), "text/css; charset=utf-8");
          return;
        }
        if (pathname === "/static/landing.js") {
          serveFile(response, path.join(publicDir, "landing.js"), "text/javascript; charset=utf-8");
          return;
        }
        if (pathname.startsWith("/static/assets/")) {
          const assetName = pathname.slice("/static/assets/".length);
          const assetPath = path.join(publicDir, "assets", assetName);
          const extension = path.extname(assetName).toLowerCase();
          const contentType = extension === ".svg" ? "image/svg+xml" : extension === ".png" ? "image/png" : "application/octet-stream";
          serveFile(response, assetPath, contentType);
          return;
        }
        next();
      });
    }
  };
}

export default defineConfig(({ command }) => ({
  plugins: [landingDevPlugin(), react()],
  root: "frontend",
  // Development is served directly by Vite at /app. Production HTML is
  // served by FastAPI at /app and loads its compiled assets from /app-static.
  base: command === "build" ? "/app-static/" : "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets"
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiProxyTarget,
      "/uploads": apiProxyTarget
    }
  }
}));
