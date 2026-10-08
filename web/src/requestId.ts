type SecureRandomSource = {
  randomUUID?: () => string;
  getRandomValues?: (bytes: Uint8Array) => Uint8Array;
};
const HEX = '0123456789abcdef';

/** 缺少 randomUUID 的 WebView 使用安全随机数；绝不降级到 Math.random。 */
export function createRequestId(
  source: SecureRandomSource | null = window.crypto as SecureRandomSource,
): string {
  if (!source) throw new Error('安全随机数不可用');
  if (typeof source.randomUUID === 'function') return source.randomUUID.call(source);
  if (typeof source.getRandomValues !== 'function') throw new Error('安全随机数不可用');
  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  let hex = '';
  for (const byte of bytes) hex += HEX[byte >>> 4] + HEX[byte & 0x0f];
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join('-');
}
