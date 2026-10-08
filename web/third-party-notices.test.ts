// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { thirdPartyNotices } from './third-party-notices';

describe('锁定前端包完整许可收集', () => {
  it('包含 React 和 Tauri 的完整许可且不输出本机路径', () => {
    const notices = thirdPartyNotices();
    for (const name of ['react', 'react-dom', 'scheduler', '@tauri-apps/api']) {
      expect(notices).toContain(`${name} `);
    }
    expect(notices).toContain('@tauri-apps/api 2.12.1');
    expect(notices).toContain('Permission is hereby granted, free of charge');
    expect(notices).toContain('Apache License');
    expect(notices).not.toContain(process.cwd());
    expect(notices).not.toMatch(/\b[A-Za-z]:[\\/]|file:\/\/|node_modules[\\/]/);
  });

  it('缺失 Apache 许可时不能静默生成残缺清单', () => {
    expect(() =>
      thirdPartyNotices((path) => {
        if (path.endsWith('LICENSE-APACHE-2.0')) throw new Error('许可证文件缺失');
        return readFileSync(path, 'utf8');
      }),
    ).toThrow('许可证文件缺失');
  });

  it('空许可必须阻止生成清单', () => {
    expect(() =>
      thirdPartyNotices((path) =>
        path.endsWith('LICENSE-MIT') ? ' \n' : readFileSync(path, 'utf8'),
      ),
    ).toThrow('缺少完整许可证：@tauri-apps/api/LICENSE-MIT');
  });
});
