import { spawn, spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const directory = new URL('.', import.meta.url);
const files = readdirSync(directory).filter((name) => name.endsWith('.test.mjs')).sort();
const child = spawn(process.execPath, [
  '--test', '--test-timeout=60000',
  ...files.map((name) => fileURLToPath(new URL(name, directory))),
], { stdio: 'inherit', windowsHide: true, detached: process.platform !== 'win32' });
let expired = false;
const timer = setTimeout(() => {
  expired = true;
  process.stderr.write('桌面静态测试超过 60 秒上限，正在停止本次测试进程。\n');
  if (process.platform === 'win32') {
    // 仅终止当前脚本直接启动的测试 PID 及其子进程，不按进程名批量终止。
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  } else {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { /* 刚好自然退出。 */ }
  }
}, 60_000);
child.on('error', () => {
  clearTimeout(timer);
  process.stderr.write('无法启动桌面静态测试进程。\n');
  process.exitCode = 1;
});
child.on('exit', (code) => {
  clearTimeout(timer);
  process.exitCode = expired ? 124 : (code ?? 1);
});
