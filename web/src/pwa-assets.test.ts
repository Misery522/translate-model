import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { inflateSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';

import { isPublicShellAsset } from '../scripts/static-assets.mjs';

const webRoot = process.cwd();
const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const background = [0xf3, 0xf5, 0xef, 0xff] as const;
const expectedHashes: Record<string, string> = {
  'pet-icon-192.png': '10083ea533259f3826be35a56a2717895da3c16afd57164cc9b7a7e4e32f7bb6',
  'pet-icon-512.png': '40ea77513eaffab71b585bb8305bd67fd951c7a3afd0a2086c0f927d17833fa2',
  'pet-icon-maskable-512.png': 'aaffcba5ed361acff54d1a05c8d04c41276cc6c6b7ff8f75683fd0da8ff83c34',
  'apple-touch-icon.png': '1bef64e1776e2359f2097d5d8309f2bc9f121bb121c6c1b1a6d41e3419afe6b5',
};

interface DecodedPng {
  bytes: Buffer;
  width: number;
  height: number;
  pixels: Buffer;
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function paeth(left: number, above: number, upperLeft: number): number {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

// 只实现仓库图标使用的非隔行 8-bit RGBA，遇到其他 PNG 模式应明确失败。
function decodePngBytes(bytes: Buffer): DecodedPng {
  if (!bytes.subarray(0, pngSignature.length).equals(pngSignature)) {
    throw new Error('PNG 签名无效');
  }

  let offset = pngSignature.length;
  let width = 0;
  let height = 0;
  let sawHeader = false;
  let sawEnd = false;
  let idatFinished = false;
  const idat: Buffer[] = [];

  while (offset < bytes.length) {
    if (offset + 12 > bytes.length) throw new Error('PNG 数据块被截断');
    const length = bytes.readUInt32BE(offset);
    const end = offset + 12 + length;
    if (end > bytes.length) throw new Error('PNG 数据块长度越界');

    const typeBytes = bytes.subarray(offset + 4, offset + 8);
    const type = typeBytes.toString('ascii');
    if (!/^[A-Za-z]{4}$/.test(type)) throw new Error('PNG 数据块类型无效');
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    const actualCrc = bytes.readUInt32BE(offset + 8 + length);
    const expectedCrc = crc32(Buffer.concat([typeBytes, data]));
    if (actualCrc !== expectedCrc) throw new Error(`${type} 数据块 CRC 无效`);

    if (!sawHeader && type !== 'IHDR') throw new Error('IHDR 必须是首个数据块');
    if (type === 'IHDR') {
      if (sawHeader || length !== 13) throw new Error('IHDR 数据块无效');
      sawHeader = true;
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      if (
        width === 0 ||
        height === 0 ||
        data[8] !== 8 ||
        data[9] !== 6 ||
        data[10] !== 0 ||
        data[11] !== 0 ||
        data[12] !== 0
      ) {
        throw new Error('只允许非隔行 8-bit RGBA PNG');
      }
    } else if (type === 'IDAT') {
      if (idatFinished) throw new Error('IDAT 数据块必须连续');
      idat.push(data);
    } else {
      if (idat.length > 0) idatFinished = true;
      if (type === 'IEND') {
        if (length !== 0) throw new Error('IEND 数据块必须为空');
        sawEnd = true;
        if (end !== bytes.length) throw new Error('IEND 后存在多余数据');
      }
    }
    offset = end;
    if (sawEnd) break;
  }

  if (!sawHeader || idat.length === 0 || !sawEnd || offset !== bytes.length) {
    throw new Error('PNG 缺少必要数据块');
  }

  const bytesPerPixel = 4;
  const stride = width * bytesPerPixel;
  const packed = inflateSync(Buffer.concat(idat));
  if (packed.length !== height * (stride + 1)) throw new Error('IDAT 解压长度无效');

  const pixels = Buffer.alloc(width * height * bytesPerPixel);
  let previous = Buffer.alloc(stride);
  for (let row = 0; row < height; row += 1) {
    const packedOffset = row * (stride + 1);
    const filter = packed[packedOffset];
    if (filter === undefined || filter > 4) throw new Error('PNG 行过滤器无效');
    const source = packed.subarray(packedOffset + 1, packedOffset + 1 + stride);
    const decoded = Buffer.alloc(stride);
    for (let column = 0; column < stride; column += 1) {
      const left = column >= bytesPerPixel ? decoded[column - bytesPerPixel] : 0;
      const above = previous[column];
      const upperLeft = column >= bytesPerPixel ? previous[column - bytesPerPixel] : 0;
      const predictor =
        filter === 0
          ? 0
          : filter === 1
            ? left
            : filter === 2
              ? above
              : filter === 3
                ? Math.floor((left + above) / 2)
                : paeth(left, above, upperLeft);
      decoded[column] = (source[column] + predictor) & 0xff;
    }
    decoded.copy(pixels, row * stride);
    previous = decoded;
  }
  return { bytes, width, height, pixels };
}

function decodePng(name: string): DecodedPng {
  return decodePngBytes(readFileSync(resolve(webRoot, 'public', name)));
}

function pixelAt(image: DecodedPng, x: number, y: number): number[] {
  const offset = (y * image.width + x) * 4;
  return [...image.pixels.subarray(offset, offset + 4)];
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
  ])('%s 是结构完整且可解码的 %ix%i PNG', (name, size) => {
    const image = decodePng(name);
    expect([image.width, image.height]).toEqual([size, size]);
    expect(createHash('sha256').update(image.bytes).digest('hex')).toBe(expectedHashes[name]);
  });

  it('损坏 CRC 或截断 IEND 时验证会失败', () => {
    const bytes = readFileSync(resolve(webRoot, 'public/pet-icon-192.png'));
    const corrupted = Buffer.from(bytes);
    corrupted[40] ^= 1;
    expect(() => decodePngBytes(corrupted)).toThrow(/CRC/);
    expect(() => decodePngBytes(bytes.subarray(0, -1))).toThrow(/截断|越界|必要数据块/);
  });

  it.each(['pet-icon-maskable-512.png', 'apple-touch-icon.png'])(
    '%s 使用完整不透明底色',
    (name) => {
      const image = decodePng(name);
      for (const [x, y] of [
        [0, 0],
        [image.width - 1, 0],
        [0, image.height - 1],
        [image.width - 1, image.height - 1],
      ]) {
        expect(pixelAt(image, x, y)).toEqual(background);
      }
      for (let alpha = 3; alpha < image.pixels.length; alpha += 4) {
        expect(image.pixels[alpha]).toBe(0xff);
      }
    },
  );

  it('maskable 图标的非背景内容位于中心 80% 安全圆内', () => {
    const image = decodePng('pet-icon-maskable-512.png');
    const centerX = (image.width - 1) / 2;
    const centerY = (image.height - 1) / 2;
    const safeRadiusSquared = (image.width * 0.4) ** 2;
    let foregroundPixels = 0;
    let furthestDistanceSquared = 0;
    for (let y = 0; y < image.height; y += 1) {
      for (let x = 0; x < image.width; x += 1) {
        const pixel = pixelAt(image, x, y);
        if (pixel.every((channel, index) => channel === background[index])) continue;
        foregroundPixels += 1;
        furthestDistanceSquared = Math.max(
          furthestDistanceSquared,
          (x - centerX) ** 2 + (y - centerY) ** 2,
        );
      }
    }
    expect(foregroundPixels).toBeGreaterThan(image.width * image.height * 0.1);
    expect(furthestDistanceSquared).toBeLessThanOrEqual(safeRadiusSquared);
  });

  it('Apple 图标主体为系统裁切保留至少 10% 四周余量', () => {
    const image = decodePng('apple-touch-icon.png');
    const inset = Math.floor(image.width * 0.1);
    let minX = image.width;
    let minY = image.height;
    let maxX = -1;
    let maxY = -1;
    for (let y = 0; y < image.height; y += 1) {
      for (let x = 0; x < image.width; x += 1) {
        const pixel = pixelAt(image, x, y);
        if (pixel.every((channel, index) => channel === background[index])) continue;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
    expect([minX, minY, maxX, maxY]).toEqual([25, 24, 154, 158]);
    expect(
      Math.min(minX, minY, image.width - 1 - maxX, image.height - 1 - maxY),
    ).toBeGreaterThanOrEqual(inset);
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
