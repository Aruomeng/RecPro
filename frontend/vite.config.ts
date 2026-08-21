import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  build: {
    // Preserve prior immutable assets so repeated builds never remove files.
    emptyOutDir: false,
    // ECharts is registered per lazy route; the remaining shared rendering
    // primitives form one measured 512 kB chunk rather than a monolithic
    // all-chart bundle.  Keep the warning threshold just above that baseline.
    chunkSizeWarningLimit: 540,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
});
