import assert from 'node:assert/strict';
import { lstatSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { isPublicShellAsset } from './static-assets.mjs';

const scriptsRoot = dirname(fileURLToPath(import.meta.url));
const distRoot = resolve(scriptsRoot, '..', 'dist');
const serviceWorker = readFileSync(resolve(distRoot, 'sw.js'), 'utf8');

assert(!serviceWorker.includes('__ASSETS__'), 'sw.js 仍包含静态资源模板占位符');
assert(!serviceWorker.includes('__BUILD_HASH__'), 'sw.js 仍包含构建哈希模板占位符');

const pathsMatch = serviceWorker.match(/^const STATIC_PATHS = (\[[^\n]+\]);$/m);
assert(pathsMatch, 'sw.js 缺少可解析的 STATIC_PATHS');
const staticPaths = JSON.parse(pathsMatch[1]);
assert(Array.isArray(staticPaths) && staticPaths.length > 0, 'STATIC_PATHS 必须是非空数组');
assert(
    staticPaths.every((path) => typeof path === 'string'),
    'STATIC_PATHS 只能包含字符串',
);
assert.deepEqual(staticPaths, [...new Set(staticPaths)], 'STATIC_PATHS 不得包含重复项');
assert.deepEqual(staticPaths, [...staticPaths].sort(), 'STATIC_PATHS 必须稳定排序');

const cacheMatch = serviceWorker.match(/^const CACHE_NAME = '([^']+)';$/m);
assert(cacheMatch, 'sw.js 缺少可解析的 CACHE_NAME');
assert.match(cacheMatch[1], /^yijing-shell-[0-9a-f]{16}$/, 'CACHE_NAME 必须包含 16 位构建哈希');

const expectedPaths = readdirSync(distRoot, { recursive: true, encoding: 'utf8' })
    .map((path) => path.replaceAll('\\', '/'))
    .filter((path) => lstatSync(resolve(distRoot, path)).isFile())
    .filter(isPublicShellAsset)
    .sort()
    .map((path) => `/${path}`);
assert.deepEqual(staticPaths, expectedPaths, 'STATIC_PATHS 必须与 dist 公开壳文件完全一致');

for (const required of [
    '/index.html',
    '/manifest.webmanifest',
    '/pet-icon.svg',
    '/pet-icon-192.png',
    '/pet-icon-512.png',
    '/pet-icon-maskable-512.png',
    '/apple-touch-icon.png',
]) {
    assert(staticPaths.includes(required), `STATIC_PATHS 缺少 ${required}`);
}
assert(
    staticPaths.some((path) => /^\/assets\/[^/]+\.js$/.test(path)),
    'STATIC_PATHS 缺少 JS',
);
assert(
    staticPaths.some((path) => /^\/assets\/[^/]+\.css$/.test(path)),
    'STATIC_PATHS 缺少 CSS',
);

for (const publicPath of staticPaths) {
    assert(publicPath.startsWith('/'), `缓存路径必须以 / 开头：${publicPath}`);
    assert(!/[?#\\]/.test(publicPath), `缓存路径不得含查询、片段或反斜杠：${publicPath}`);
    assert(!publicPath.split('/').includes('..'), `缓存路径不得越界：${publicPath}`);
    assert(publicPath !== '/sw.js', 'sw.js 不得缓存自身');
    assert(publicPath !== '/THIRD_PARTY_LICENSES.txt', '许可清单不得进入静态缓存');
    assert(publicPath !== '/api' && !publicPath.startsWith('/api/'), 'API 不得进入静态缓存');

    const candidate = resolve(distRoot, publicPath.slice(1));
    const insideDist = relative(distRoot, candidate);
    assert(
        insideDist && !insideDist.startsWith('..') && !isAbsolute(insideDist),
        `缓存路径越界：${publicPath}`,
    );
    assert(lstatSync(candidate).isFile(), `缓存路径必须对应普通文件：${publicPath}`);
}

console.log(`已验证 ${staticPaths.length} 个 PWA 静态壳资源。`);
