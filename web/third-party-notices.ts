import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';

const require = createRequire(import.meta.url);
const packages = [
  ['react', ['LICENSE']],
  ['react-dom', ['LICENSE']],
  ['scheduler', ['LICENSE']],
  ['@tauri-apps/api', ['LICENSE-MIT', 'LICENSE-APACHE-2.0']],
] as const;

export function thirdPartyNotices(
  readText: (path: string) => string = (path) => readFileSync(path, 'utf8'),
): string {
  const notices = packages.map(([name, filenames]) => {
    const packagePath = require.resolve(`${name}/package.json`);
    const metadata = JSON.parse(readText(packagePath)) as { version: string };
    // 许可缺失或为空必须阻止构建，不能生成看似完整的发布清单。
    const license = filenames
      .map((filename) => {
        const text = readText(resolve(dirname(packagePath), filename)).trim();
        if (!text) throw new Error(`缺少完整许可证：${name}/${filename}`);
        return text;
      })
      .join('\n');
    return `${name} ${metadata.version}\n${'='.repeat(60)}\n${license}\n`;
  });
  return `${notices.join('\n')}\n`;
}
