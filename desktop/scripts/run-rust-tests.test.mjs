import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const windowsOnly = { skip: process.platform !== 'win32' };
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const runnerPath = join(scriptDirectory, 'run-rust-tests.ps1');
const powerShell = 'pwsh.exe';

function runRunner(mode, { timeoutSeconds = 10, statePath, env = {} } = {}) {
  const args = [
    '-NoLogo', '-NoProfile', '-NonInteractive',
    '-File', runnerPath,
    '-TimeoutSeconds', String(timeoutSeconds),
    '-TestMode', mode,
  ];
  if (statePath) args.push('-TestStatePath', statePath);
  return spawnSync(powerShell, args, {
    encoding: 'utf8',
    env: { ...process.env, YIJING_RUST_RUNNER_SELF_TEST: '1', ...env },
    maxBuffer: 1024 * 1024,
    timeout: 15_000,
    windowsHide: true,
  });
}

function isProcessAlive(pid) {
  const result = spawnSync('tasklist.exe', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], {
    encoding: 'utf8',
    windowsHide: true,
  });
  return result.status === 0 && result.stdout.includes(`"${pid}"`);
}

function stopOwnedProcessTree(pid) {
  if (Number.isSafeInteger(pid) && pid > 0 && isProcessAlive(pid)) {
    spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
      encoding: 'utf8',
      stdio: 'ignore',
      windowsHide: true,
    });
  }
}

test('Rust 运行器同时排空大量 stdout 和 stderr', windowsOnly, () => {
  const result = runRunner('capture');
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /CAPTURE_STDOUT_OK/);
  assert.match(result.stderr, /CAPTURE_STDERR_OK/);
  assert.ok(result.stdout.length > 128 * 1024);
  assert.ok(result.stderr.length > 128 * 1024);
});

test('Rust 运行器原样传播测试进程退出码并保留双流诊断', windowsOnly, () => {
  const result = runRunner('failure');
  assert.equal(result.error, undefined);
  assert.equal(result.status, 37);
  assert.match(result.stdout, /FAILURE_STDOUT_OK/);
  assert.match(result.stderr, /FAILURE_STDERR_OK/);
});

test('Rust 运行器过滤环境秘密、认证头、Cookie 和 GitHub 令牌', windowsOnly, () => {
  const secret = 'runner-secret-value-9f4c7a';
  const sameLengthToken = 'runner-token-value--4e8d2b';
  const githubToken = 'github_pat_abcdefghijklmnopqrstuvwxyz0123456789';
  assert.equal(secret.length, sameLengthToken.length);
  const result = runRunner('sensitive', {
    env: { YIJING_TEST_SECRET: secret, YIJING_TEST_TOKEN: sameLengthToken },
  });
  const combined = `${result.stdout}\n${result.stderr}`;
  assert.equal(result.status, 0, combined);
  assert.ok(!combined.includes(secret));
  assert.ok(!combined.includes(sameLengthToken));
  assert.ok(!combined.includes(githubToken));
  for (const leakedValue of [
    'dXNlcjpwYXNz', 'abc123', 'theme=dark', 'csrf=def456',
    'username="demo"', 'digest-value', 'server456', 'Path=/', 'HttpOnly',
  ]) {
    assert.ok(!combined.includes(leakedValue), `敏感头仍包含 ${leakedValue}`);
  }
  assert.match(combined, /YIJING_TEST_SECRET=\[REDACTED\]/);
  assert.match(combined, /^Authorization: \[REDACTED\]$/m);
  assert.match(combined, /^Proxy-Authorization: \[REDACTED\]$/m);
  assert.match(combined, /^Cookie: \[REDACTED\]$/m);
  assert.match(combined, /^Set-Cookie: \[REDACTED\]$/m);
  assert.ok((combined.match(/\[REDACTED\]/g) ?? []).length >= 9);
});

test('Rust 运行器超时只终止自己创建的进程树', windowsOnly, async () => {
  const temporaryDirectory = mkdtempSync(join(tmpdir(), 'yijing-rust-runner-'));
  const statePath = join(temporaryDirectory, 'child.pid');
  const unrelated = spawn(powerShell, [
    '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30',
  ], { stdio: 'ignore', windowsHide: true });
  let ownedChildPid;

  try {
    assert.ok(unrelated.pid > 0);
    const result = runRunner('timeout', { timeoutSeconds: 1, statePath });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 124, result.stderr);
    assert.match(result.stdout, /Rust 测试超过 1 秒上限/);
    assert.ok(existsSync(statePath));
    ownedChildPid = Number.parseInt(readFileSync(statePath, 'utf8'), 10);
    assert.ok(Number.isSafeInteger(ownedChildPid) && ownedChildPid > 0);

    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(isProcessAlive(ownedChildPid), false, '测试夹具的子进程仍在运行');
    assert.equal(isProcessAlive(unrelated.pid), true, '无关进程不应被终止');
  } finally {
    stopOwnedProcessTree(ownedChildPid);
    stopOwnedProcessTree(unrelated.pid);
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
});

test('Rust 运行器拒绝未经显式授权的测试夹具入口', windowsOnly, () => {
  const cleanEnvironment = { ...process.env };
  delete cleanEnvironment.YIJING_RUST_RUNNER_SELF_TEST;
  const result = spawnSync(powerShell, [
    '-NoLogo', '-NoProfile', '-NonInteractive',
    '-File', runnerPath,
    '-TestMode', 'failure',
  ], {
    encoding: 'utf8',
    env: cleanEnvironment,
    timeout: 10_000,
    windowsHide: true,
  });
  assert.equal(result.status, 64);
  assert.match(result.stderr, /测试夹具入口只允许由仓库回归测试显式启用/);
});
