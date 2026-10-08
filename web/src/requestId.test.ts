import { describe, expect, it, vi } from 'vitest';
import { createRequestId } from './requestId';

describe('安全客户端请求编号', () => {
  it('优先使用浏览器原生 randomUUID 并保持 this 绑定', () => {
    const source = {
      marker: 'native',
      randomUUID(this: { marker: string }) {
        expect(this.marker).toBe('native');
        return '123e4567-e89b-42d3-a456-426614174000';
      },
      getRandomValues: vi.fn(),
    };

    expect(createRequestId(source)).toBe('123e4567-e89b-42d3-a456-426614174000');
    expect(source.getRandomValues).not.toHaveBeenCalled();
  });

  it.each([
    [0x00, '00000000-0000-4000-8000-000000000000'],
    [0xff, 'ffffffff-ffff-4fff-bfff-ffffffffffff'],
  ])('旧 WebView 使用 getRandomValues 生成 RFC 4122 v4：%i', (fill, expected) => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      expect(bytes).toBeInstanceOf(Uint8Array);
      expect(bytes).toHaveLength(16);
      bytes.fill(fill);
      return bytes;
    });
    const unsafeRandom = vi.spyOn(Math, 'random').mockImplementation(() => {
      throw new Error('Math.random 不得用于请求编号');
    });

    expect(createRequestId({ getRandomValues })).toBe(expected);
    expect(getRandomValues).toHaveBeenCalledTimes(1);
    expect(unsafeRandom).not.toHaveBeenCalled();
  });

  it('缺少安全随机源时明确拒绝', () => {
    expect(() => createRequestId(null)).toThrow('安全随机数');
    expect(() => createRequestId({})).toThrow('安全随机数');
  });
});
