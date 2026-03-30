import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  // In Docker: VITE_PROXY_TARGET=http://pdf-backend:8000, locally falls back to localhost
  const apiUrl = env.VITE_PROXY_TARGET || "http://localhost:8000"
  return {
    plugins: [react(), tailwindcss()],
    base: env.VITE_BASE_URL || "/",
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        "/api": { target: apiUrl, changeOrigin: true },
        "/static": { target: apiUrl, changeOrigin: true },
        "/ws": { target: apiUrl.replace(/^http/, "ws"), ws: true },
      },
    },
  }
})
