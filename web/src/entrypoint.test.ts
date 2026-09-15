import { describe, expect, it } from 'vitest';
import { selectClient } from './entrypoint';

describe('宿主入口隔离', () => {
  it.each(['', '?view=pet', '?view=pet&origin=https://untrusted.example'])(
    '普通网页 %s 不能启用原生桥',
    (search) => expect(selectClient(false, search)).toBe('web'),
  );
  it('仅接受原生宿主的显式宠物入口', () => {
    expect(selectClient(true, '?view=pet')).toBe('pet');
    expect(selectClient(true, '')).toBe('blocked');
    expect(selectClient(true, '?view=web')).toBe('blocked');
  });
});
