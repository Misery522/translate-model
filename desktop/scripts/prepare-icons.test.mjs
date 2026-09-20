import assert from 'node:assert/strict';
import test from 'node:test';
import { inflateSync } from 'node:zlib';
import { crc32, makeIcons } from './prepare-icons.mjs';

test('CRC32 标准向量', () => assert.equal(crc32(Buffer.from('123456789')), 0xcbf43926));
test('PNG 与 ICO 原创构建资源有效且确定', () => {
  const { png, ico } = makeIcons();
  assert.deepEqual(png, makeIcons().png);
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  let offset = 8;
  const payload = [];
  while (offset < png.length) {
    const size = png.readUInt32BE(offset);
    const type = png.subarray(offset + 4, offset + 8).toString();
    assert.equal(crc32(png.subarray(offset + 4, offset + 8 + size)), png.readUInt32BE(offset + 8 + size));
    if (type === 'IDAT') payload.push(png.subarray(offset + 8, offset + 8 + size));
    offset += 12 + size;
  }
  assert.equal(inflateSync(Buffer.concat(payload)).length, 64 * 257);
  assert.equal(ico.readUInt16LE(2), 1);
  assert.equal(ico.readUInt16LE(4), 1);
  assert.equal(ico.readUInt32LE(14), png.length);
  assert.deepEqual(ico.subarray(22), png);
});
