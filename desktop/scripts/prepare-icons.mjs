// 构建时生成原创几何图标；没有下载或第三方图片素材。
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';

export function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const name = Buffer.from(type);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([length, name, data, checksum]);
}
export function makeIcons() {
  const size = 64;
  const rows = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const bubble = x >= 6 && x < 58 && y >= 6 && y < 52;
      const tail = x >= 12 && x < 24 && y >= 52 && y < 60 - (x - 12) / 2;
      const eye = ((x >= 20 && x < 26) || (x >= 40 && x < 46)) && y >= 23 && y < 31;
      const color = !(bubble || tail) ? [0, 0, 0, 0] : eye ? [255, 255, 255, 255] : [20, 130, 120, 255];
      rows.set(color, y * (size * 4 + 1) + 1 + x * 4);
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4); ihdr[8] = 8; ihdr[9] = 6;
  const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
  // Windows Vista+ 接受 ICO 中嵌入 PNG；单一 64x64 图标足够首版 alpha。
  const icoHeader = Buffer.alloc(22);
  icoHeader.writeUInt16LE(1, 2); icoHeader.writeUInt16LE(1, 4);
  icoHeader[6] = size; icoHeader[7] = size;
  icoHeader.writeUInt16LE(1, 10); icoHeader.writeUInt16LE(32, 12);
  icoHeader.writeUInt32LE(png.length, 14); icoHeader.writeUInt32LE(22, 18);
  return { png, ico: Buffer.concat([icoHeader, png]) };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const directory = resolve(dirname(fileURLToPath(import.meta.url)), '../src-tauri/icons');
  const icons = makeIcons();
  mkdirSync(directory, { recursive: true });
  for (const extension of ['png', 'ico']) writeFileSync(resolve(directory, `icon.${extension}`), icons[extension]);
  console.log('已生成原创构建图标（忽略的构建产物）。');
}
