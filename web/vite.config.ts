import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.SORVIA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": api,
      "/healthz": api,
      "/readyz": api,
      "/docs": api,
      "/openapi.json": api,
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 800 },
});
