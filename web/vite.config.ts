import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import { thirdPartyNotices } from './third-party-notices.ts';

// 构建时生成精确静态白名单；API、用户输入及响应不进入缓存。
function staticShell() {
  const root = fileURLToPath(new URL('.', import.meta.url));
  return {
    name: 'yijing-static-shell',
    closeBundle() {
      const output = resolve(root, 'dist');
      // 从锁定安装包携带完整许可，不依赖压缩文件中的简短版权注释。
      writeFileSync(resolve(output, 'THIRD_PARTY_LICENSES.txt'), thirdPartyNotices());
      const assets = readdirSync(output, { recursive: true, encoding: 'utf8' })
        .map((path) => path.replaceAll('\\', '/'))
        .filter((path) =>
          /^(index\.html|pet-icon\.svg|manifest\.webmanifest|assets\/[^/]+\.(js|css|svg|woff2))$/.test(
            path,
          ),
        )
        .sort();
      const hash = createHash('sha256');
      for (const asset of assets) hash.update(asset).update(readFileSync(resolve(output, asset)));
      const template = readFileSync(resolve(root, 'src/service-worker.js'), 'utf8');
      writeFileSync(
        resolve(output, 'sw.js'),
        template
          .replace('/*__ASSETS__*/ []', JSON.stringify(assets.map((path) => `/${path}`)))
          .replace('__BUILD_HASH__', hash.digest('hex').slice(0, 16)),
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), staticShell()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false } },
  },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    testTimeout: 5000,
    hookTimeout: 5000,
    maxWorkers: 2,
    restoreMocks: true,
  },
});
