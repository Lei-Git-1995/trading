import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "node:path";
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:18081',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: resolve(__dirname, "../static"),
    emptyOutDir: true,
    // 固定产物文件名，便于 embed / 缓存策略；主包打成一个 JS，样式一个 CSS
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        entryFileNames: "assets/index.js",
        assetFileNames: (assetInfo) => {
          const n = assetInfo.names?.[0] ?? assetInfo.name ?? "";
          if (typeof n === "string" && n.endsWith(".css")) {
            return "assets/index.css";
          }
          return "assets/[name][extname]";
        },
      },
    },
  },
});
