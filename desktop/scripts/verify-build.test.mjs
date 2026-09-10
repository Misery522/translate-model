import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const readWorkflow = () => read('../../.github/workflows/desktop.yml');

test('构建版本一致并明确将锁定参数传给 Cargo', () => {
  const pkg = JSON.parse(read('../package.json'));
  const config = JSON.parse(read('../src-tauri/tauri.conf.json'));
  const cargo = read('../src-tauri/Cargo.toml');
  const lock = JSON.parse(read('../package-lock.json'));
  assert.equal(pkg.version, '0.4.0-alpha.1');
  assert.equal(config.version, pkg.version);
  assert.equal(lock.version, pkg.version);
  assert.match(cargo, /version = "0\.4\.0-alpha\.1"/);
  assert.equal(pkg.scripts.build, 'npm run prepare:icons && tauri build --bundles nsis --no-sign --ci -- --locked');
  assert.equal(pkg.scripts.test, 'node scripts/test.mjs');
});

test('活动源码工作流固定 Actions SHA 且只上传锁文件与限定格式补丁', () => {
  // 活动工作流缺失应失败，不能回退到过期模板假装门禁仍存在。
  const workflow = readWorkflow();
  const actions = [...workflow.matchAll(/uses: ([^\s#]+)/g)].map((item) => item[1]);
  const allowed = new Set([
    'actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683',
    'actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020',
    'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',
  ]);
  assert.ok(actions.length >= 3 && actions.every((item) => allowed.has(item)));
  assert.match(workflow, /contents: read/);
  assert.ok(!workflow.includes('contents: write') && !workflow.includes('secrets.'));
  assert.match(workflow, /runs-on: windows-2022/);
  assert.match(workflow, /RUSTUP_TOOLCHAIN: 1\.98\.0-x86_64-pc-windows-msvc/);
  assert.match(workflow, /node-version: "24\.18\.1"/);
  const pathBlocks = [...workflow.matchAll(/^ {10}path: \|\r?\n((?: {12}\S[^\r\n]*\r?\n)+)/gm)];
  assert.equal(pathBlocks.length, 1);
  assert.equal([...workflow.matchAll(/^ {10}path:/gm)].length, 1);
  assert.deepEqual(pathBlocks.flatMap((item) => item[1].trim().split(/\r?\n/).map((line) => line.trim())), [
    '${{ runner.temp }}/yijing-desktop-lock-review/Cargo.lock',
    '${{ runner.temp }}/yijing-desktop-lock-review/rustfmt.patch',
  ]);
  const formatList = workflow.match(/\$formatFiles = @\(([\s\S]+?)\n {10}\)/);
  assert.ok(formatList);
  assert.deepEqual([...formatList[1].matchAll(/'([^']+)'/g)].map((item) => item[1]), [
    'desktop/src-tauri/build.rs',
    'desktop/src-tauri/src/main.rs',
    'desktop/src-tauri/src/bridge.rs',
    'desktop/src-tauri/src/bridge/tests.rs',
  ]);
  assert.match(workflow, /diff --no-ext-diff --no-textconv --no-renames "--output=\$patchPath" -- \$formatFiles/);
  assert.match(workflow, /UTF8Encoding\]::new\(\$false, \$true\)/);
  assert.ok(!workflow.includes('npm --prefix desktop run build'));
  assert.ok(!workflow.includes('--bundles') && !workflow.includes('bundle/nsis'));
  assert.ok(!workflow.includes('installer.outputs') && !workflow.includes('SHA256SUMS'));
  assert.match(workflow, /cargo fmt --manifest-path desktop\/src-tauri\/Cargo\.toml --all -- --check/);
  assert.match(workflow, /test "\$COMMITTED_LOCK" = true/);
  assert.match(workflow, /cargo test --locked --no-run/);
  assert.match(workflow, /pwsh -NoProfile -File desktop\/scripts\/run-rust-tests\.ps1/);
});

test('固定 Rust 审计使用独立工具根与明确锁文件，不允许静默例外', () => {
  const workflow = readWorkflow();
  assert.match(workflow, /cargo install cargo-audit --version 0\.22\.2 --locked --no-default-features --root \$toolRoot/);
  assert.match(workflow, /\$toolRoot = Join-Path \$env:RUNNER_TEMP 'yijing-rust-audit-tools'/);
  assert.match(workflow, /\$lockfile = Join-Path \$env:GITHUB_WORKSPACE 'desktop\/src-tauri\/Cargo\.lock'/);
  assert.match(workflow, /& \$auditExecutable audit --file \$lockfile --deny warnings --db \$database --url https:\/\/github\.com\/RustSec\/advisory-db\.git/);
  assert.match(workflow, /Implicit cargo-audit configuration is not allowed/);
  assert.ok(!/--(?:ignore|stale|no-fetch|no-yanked)(?:[=\s]|$)|audit fix/.test(workflow));
  assert.match(workflow, /Install the fixed Rust audit tool[^\n]*\n {8}if: steps\.lock\.outputs\.present == 'true'\n {8}timeout-minutes: 15/);
  assert.match(workflow, /Audit the explicit committed Cargo lockfile[^\n]*\n {8}if: steps\.lock\.outputs\.present == 'true'\n {8}timeout-minutes: 5/);
});

test('Rust 测试计时器只终止自己创建的进程树', () => {
  const runner = read('run-rust-tests.ps1');
  assert.match(runner, /ValidateRange\(1, 60\)/);
  assert.match(runner, /CreateNoWindow = \$true/);
  assert.match(runner, /\$testProcess\.Start\(\)/);
  assert.match(runner, /WaitForExit\(\$TimeoutSeconds \* 1000\)/);
  assert.match(runner, /\$testProcess\.Kill\(\$true\)/);
  assert.ok(!runner.includes('Get-Process') && !runner.includes('Stop-Process'));
});

test('编译与严格安全审计独立运行且共同决定最终门禁', () => {
  const workflow = readWorkflow();
  const sections = workflow.match(/^  windows:([\s\S]+?)^  audit:([\s\S]+?)^  required:([\s\S]+)$/m);
  assert.ok(sections);
  const [, build, audit, required] = sections;
  assert.match(build, /cargo test --locked --no-run/);
  assert.ok(!build.includes('auditExecutable') && !/^    needs:/m.test(build));
  assert.match(audit, /git ls-files --error-unmatch -- desktop\/src-tauri\/Cargo\.lock/);
  assert.match(audit, /Audit requires a reviewed and committed Cargo\.lock/);
  assert.match(audit, /audit --file \$lockfile --deny warnings/);
  assert.ok(!/^    needs:/m.test(audit));
  assert.match(required, /needs: \[windows, audit\]/);
  assert.match(required, /BUILD_RESULT: \$\{\{ needs\.windows\.result \}\}/);
  assert.match(required, /AUDIT_RESULT: \$\{\{ needs\.audit\.result \}\}/);
  assert.match(required, /test "\$BUILD_RESULT" = success/);
  assert.match(required, /test "\$AUDIT_RESULT" = success/);
  assert.match(required, /test "\$COMMITTED_LOCK" = true/);
  assert.ok(!workflow.includes('continue-on-error'));
});
