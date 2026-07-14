import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: "frontend",
  base: "/static/react/",
  build: {
    outDir: "../src/api/static/react",
    emptyOutDir: true,
    assetsDir: "assets"
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8021",
      "/static": "http://127.0.0.1:8021",
      "/uploads": "http://127.0.0.1:8021"
    }
  }
});
