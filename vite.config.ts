import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

function manualChunks(id: string): string | undefined {
  const normalized = id.replaceAll("\\", "/");
  if (!normalized.includes("/node_modules/")) return undefined;
  if (normalized.includes("/node_modules/@supabase/")) return "supabase";
  if (
    normalized.includes("/node_modules/react/") ||
    normalized.includes("/node_modules/react-dom/") ||
    normalized.includes("/node_modules/react-router/") ||
    normalized.includes("/node_modules/react-router-dom/")
  ) {
    return "react";
  }
  return undefined;
}

export default defineConfig({
  envDir: ".",
  plugins: [react()],
  server: {
    host: "localhost",
    port: 4174,
  },
  preview: {
    host: "localhost",
    port: 4174,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
});
