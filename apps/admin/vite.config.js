import { defineConfig } from "vite";

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${process.env.APP_PORT ?? "8001"}`;

export default defineConfig({
  root: "apps/admin",
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    host: "127.0.0.1",
    port: 5176,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
});
