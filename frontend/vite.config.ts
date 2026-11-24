import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks only to Vite, which forwards API and WebSocket calls
// to FastAPI. Production does the same through Caddy, so the app always uses
// same-origin paths and never needs CORS.
const api = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": api,
      "/ws": { target: api, ws: true },
    },
  },
});
