import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { isPublicShellAsset } from '../scripts/static-assets.mjs';

const webRoot = process.cwd();

function pngDimensions(name: string) {
  const bytes = readFileSync(resolve(webRoot, 'public', name));
  expect([...bytes.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  return { bytes, size: [bytes.readUInt32BE(16), bytes.readUInt32BE(20)] };
}

describe('PWA 安装图标', () => {
  it('manifest 为普通安装和 maskable 场景声明标准 PNG', () => {
    const manifest = JSON.parse(
      readFileSync(resolve(webRoot, 'public/manifest.webmanifest'), 'utf8'),
    ) as { icons: Array<{ src: string; sizes: string; type: string; purpose: string }> };
    expect(manifest.icons).toEqual([
      { src: '/pet-icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/pet-icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      {
        src: '/pet-icon-maskable-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
    ]);
  });

  it.each([
    ['pet-icon-192.png', 192],
    ['pet-icon-512.png', 512],
    ['pet-icon-maskable-512.png', 512],
    ['apple-touch-icon.png', 180],
  ])('%s 是有效的 %ix%i PNG', (name, size) => {
    const image = pngDimensions(name);
    expect(image.size).toEqual([size, size]);
    expect(image.bytes.length).toBeGreaterThan(size * 5);
  });

  it('HTML 声明 Apple 图标且所有图标都进入静态壳白名单', () => {
    const html = readFileSync(resolve(webRoot, 'index.html'), 'utf8');
    expect(html).toContain(
      '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />',
    );
    for (const path of [
      'pet-icon.svg',
      'pet-icon-192.png',
      'pet-icon-512.png',
      'pet-icon-maskable-512.png',
      'apple-touch-icon.png',
    ]) {
      expect(isPublicShellAsset(path)).toBe(true);
    }
    expect(isPublicShellAsset('private-icon.png')).toBe(false);
  });
});
