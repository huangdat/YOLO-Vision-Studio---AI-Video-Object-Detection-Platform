import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: Number(env.FRONTEND_PORT || 5173),
      strictPort: true,
      proxy: {
        // Keep the browser's Host header: the backend then sees the UI's own requests as
        // same-origin, so they work under any local hostname (localhost, 127.0.0.1, a LAN
        // name) without listing it in CORS_ALLOWED_ORIGINS.
        "/api": {
          target: env.VITE_PROXY_TARGET || "http://localhost:8080",
          changeOrigin: false,
        },
      },
    },
    test: { environment: "jsdom", clearMocks: true },
  };
});
