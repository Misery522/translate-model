import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const child = spawn(process.execPath, [
  fileURLToPath(new URL('../node_modules/vitest/vitest.mjs', import.meta.url)), 'run',
  ...process.argv.slice(2),
], { stdio: 'inherit', windowsHide: true, detached: process.platform !== 'win32' });
let expired = false;
const timer = setTimeout(() => {
  expired = true;
  process.stderr.write('测试超过 60 秒上限，正在停止本次测试进程。\n');
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  } else {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { /* 进程可能刚刚退出。 */ }
  }
}, 60_000);
child.on('error', (error) => { clearTimeout(timer); process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
child.on('exit', (code) => { clearTimeout(timer); process.exitCode = expired ? 124 : (code ?? 1); });
