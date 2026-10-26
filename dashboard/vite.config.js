import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// /api/* is proxied to the API, so the dashboard can be shared through one tunnel (ngrok) on this port:
// start it with VITE_API_URL=/api (README "Share the dashboard"); the default .env keeps calling the API directly.
const api = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, host: "localhost", proxy: api, allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app"] },
  preview: { port: 4173, host: "localhost", proxy: api, allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app"] },
});
