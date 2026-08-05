import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;

export default defineConfig({
  plugins: [react()],
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
      "/api": apiProxyTarget,
      "/uploads": apiProxyTarget
    }
  }
});
