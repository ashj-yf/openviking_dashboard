/// <reference types="vitest/config" />
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@mocks": path.resolve(__dirname, "mocks"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/healthz": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: false,
    restoreMocks: true,
    // antd Form 在 jsdom 下每个 FormItem 的错误去抖定时器（约 10ms）会被
    // userEvent 的 act 包装逐键等待，含校验/提交的交互用例在本机约需 5-6s。
    testTimeout: 10000,
    // 交互型 UI 用例对时间敏感，多文件并行时会互相争抢 CPU 使 20-30s 预算的重交互
    // 用例随机超时（T6 实测并行下每次失败集合都在漂移）；改为文件级串行换取门禁确定性。
    fileParallelism: false,
  },
});
