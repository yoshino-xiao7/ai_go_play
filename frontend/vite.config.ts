import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "MANJU_");
  const api = env.MANJU_DEV_API || "http://127.0.0.1:8765";
  return {
    plugins: [react()],
    // The local server can be serving dist while an agent rebuilds the UI.
    // Keep hashed chunks needed by already-open tabs until a fresh installation.
    build: { emptyOutDir: false },
    server: { proxy: { "/api": api } },
  };
});
