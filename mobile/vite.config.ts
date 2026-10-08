import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import react from "../web/node_modules/@vitejs/plugin-react/dist/index.js";
import { defineConfig } from "../web/node_modules/vitest/dist/config.js";

const root = fileURLToPath(new URL(".", import.meta.url));
const webModules = resolve(root, "../web/node_modules");
const require = createRequire(resolve(root, "../web/package.json"));

// 复用已锁定的网页依赖，不增加第二套 React 或改变正在试用的 PWA dist。
export default defineConfig({
  root,
  base: "./",
  publicDir: false,
  server: { fs: { allow: [resolve(root, "..")] } },
  resolve: {
    alias: [
      { find: /^react$/, replacement: resolve(webModules, "react/index.js") },
      {
        find: /^react\/jsx-runtime$/,
        replacement: resolve(webModules, "react/jsx-runtime.js"),
      },
      {
        find: /^react\/jsx-dev-runtime$/,
        replacement: resolve(webModules, "react/jsx-dev-runtime.js"),
      },
      {
        find: /^react-dom$/,
        replacement: resolve(webModules, "react-dom/index.js"),
      },
      {
        find: /^react-dom\/client$/,
        replacement: resolve(webModules, "react-dom/client.js"),
      },
      {
        find: /^vitest$/,
        replacement: resolve(webModules, "vitest/dist/index.js"),
      },
      {
        find: /^@testing-library\/react$/,
        replacement: resolve(
          webModules,
          "@testing-library/react/dist/index.js",
        ),
      },
    ],
  },
  plugins: [
    react(),
    {
      name: "yijing-native-notices",
      closeBundle() {
        const notices = ["react", "react-dom", "scheduler"].map((name) => {
          const metadataPath = require.resolve(`${name}/package.json`);
          const metadata = JSON.parse(readFileSync(metadataPath, "utf8")) as {
            version: string;
          };
          const license = readFileSync(
            resolve(dirname(metadataPath), "LICENSE"),
            "utf8",
          );
          return `${name} ${metadata.version}\n${"=".repeat(60)}\n${license.trim()}\n`;
        });
        writeFileSync(
          resolve(root, "dist/THIRD_PARTY_LICENSES.txt"),
          `${notices.join("\n")}\n`,
        );
      },
    },
  ],
  build: {
    modulePreload: { polyfill: false },
    target: "chrome111",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "jsdom",
    setupFiles: [resolve(root, "../web/src/test-setup.ts")],
    testTimeout: 5000,
    hookTimeout: 5000,
    maxWorkers: 2,
    restoreMocks: true,
  },
});
