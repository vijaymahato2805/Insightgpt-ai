import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/zrender/")) return "zrender";
          if (id.includes("/node_modules/echarts/")) return "echarts";
          if (id.includes("/node_modules/echarts-for-react/")) return "echarts-react";
        },
      },
    },
  },
  server: { port: 5173, strictPort: true },
});
