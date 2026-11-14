import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Every event carries the build's release: VITE_APP_RELEASE when the deploy sets it, else the git commit.
function appRelease() {
  if (process.env.VITE_APP_RELEASE) return process.env.VITE_APP_RELEASE;
  try {
    return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "dev";
  }
}

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;

export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_APP_RELEASE": JSON.stringify(appRelease()),
  },
  root: "apps/web",
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets"
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
      },
      "/uploads": apiProxyTarget
    }
  }
});
