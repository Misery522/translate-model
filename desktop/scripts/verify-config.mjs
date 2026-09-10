import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');
const schema = JSON.parse(read('node_modules/@tauri-apps/cli/config.schema.json'));
// CLI Schema 的文件名 ASCII 正则含 \:，ECMAScript 的 u 模式拒绝该转义。
// 不修改官方 Schema；按其原始非 Unicode 正则语义编译。
const ajv = new Ajv({ allErrors: true, strict: false, unicodeRegExp: false });
ajv.addFormat('uri', (value) => URL.canParse(value));
ajv.addFormat('uuid', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
ajv.addFormat('double', { type: 'number', validate: Number.isFinite });
for (const [name, min, max] of [['uint8', 0, 255], ['uint32', 0, 4294967295], ['int32', -2147483648, 2147483647], ['int64', Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER]]) {
  ajv.addFormat(name, { type: 'number', validate: (value) => Number.isSafeInteger(value) && value >= min && value <= max });
}
const validateSchema = ajv.compile(schema);

export function validateConfiguration(config, capability, cargo, host, bridge) {
  assert.ok(validateSchema(config), '不符合固定版本 Tauri CLI 自带的官方配置 Schema');
  assert.equal(config.build.frontendDist, '../../web/dist');
  assert.equal(config.build.devUrl, undefined, '桌面仅加载已构建的本地前端');
  assert.equal(config.app.withGlobalTauri, false);
  assert.equal(config.app.windows.length, 1);
  const window = config.app.windows[0];
  assert.equal(window.label, 'main');
  assert.equal(window.create, false, '窗口必须由带导航拦截的 Rust builder 创建');
  assert.equal(window.url, 'index.html?view=pet');
  assert.equal(window.devtools, false);
  assert.equal(window.incognito, true);
  assert.equal(window.dragDropEnabled, false);
  assert.deepEqual(config.app.security.capabilities, ['main']);
  assert.equal(config.app.security.dangerousDisableAssetCspModification, false);
  const csp = config.app.security.csp;
  assert.equal(typeof csp, 'string');
  for (const directive of ["default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src ipc: http://ipc.localhost", "object-src 'none'", "frame-src 'none'", "form-action 'none'"]) {
    assert.ok(csp.split(';').some((item) => item.trim() === directive), `缺少精确 CSP 指令: ${directive}`);
  }
  assert.ok(!csp.includes('*') && !csp.includes('unsafe-eval') && !csp.includes('unsafe-inline'));
  assert.deepEqual(capability.windows, ['main']);
  assert.equal(capability.local, true);
  assert.equal(capability.remote, undefined);
  assert.deepEqual([...capability.permissions].sort(), [
    'allow-configure-backend', 'allow-backend-status', 'allow-api-request',
    'core:window:allow-start-dragging', 'core:window:allow-hide',
  ].sort());
  assert.ok(!/tauri-plugin-(shell|fs|http|clipboard|opener|store|log)/.test(cargo));
  assert.match(cargo, /reqwest = \{ version = "=[0-9.]+", default-features = false, features = \["json", "rustls"\] \}/);
  for (const token of ['.no_proxy()', 'redirect::Policy::none()', 'reqwest::retry::never()', '.timeout(Duration::from_secs(15))', '.connect_timeout(Duration::from_secs(5))', 'set_sensitive(true)', 'check_generation(generation)', 'MAX_RESPONSE_BYTES']) {
    assert.ok(bridge.includes(token), `缺少桥安全约束: ${token}`);
  }
  assert.ok(!/std::process::Command|std::fs::|cookie_store\s*\(|println!|dbg!/.test(bridge));
  assert.ok(host.includes('.on_navigation(bridge::local_navigation_allowed)'));
  assert.ok(host.includes('NewWindowResponse::Deny'));
  assert.ok(host.includes('api.prevent_close()'));
  assert.ok(host.includes('if state.accepts_command(window.label())'));
  assert.ok(host.includes('if app.state::<HostState>().begin_exit()'));
  assert.ok(host.includes('!self.exiting.swap(true, Ordering::SeqCst)'));
  assert.ok(host.includes('state.bridge.request(ApiRequest::Logout).await'));
  assert.ok(host.indexOf('state.bridge.request(ApiRequest::Logout).await') < host.indexOf('state.bridge.clear()'));
  assert.ok(host.indexOf('state.bridge.clear()') < host.indexOf('handle.exit(0)'));
  assert.ok(bridge.includes('outgoing.timeout(Duration::from_secs(3))'));
  assert.ok(bridge.includes('self.pending_logout = token.clone()'));
  assert.ok(bridge.includes('self.token.take().or_else(|| self.pending_logout.take())'));
  assert.ok(bridge.includes('response.chunk().await.map_err(|_| BridgeError::network())?'));
  assert.ok(host.includes('register("Ctrl+Shift+T")'));
  for (const command of ['configure_backend', 'backend_status', 'api_request']) {
    assert.match(host, new RegExp(`(?:async )?fn ${command}\\(`));
  }
}

export function readConfiguration() {
  return [JSON.parse(read('src-tauri/tauri.conf.json')), JSON.parse(read('src-tauri/capabilities/main.json')), read('src-tauri/Cargo.toml'), read('src-tauri/src/main.rs'), read('src-tauri/src/bridge.rs')];
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  validateConfiguration(...readConfiguration());
  if (process.argv.includes('--require-dist')) {
    assert.ok(existsSync(resolve(root, '../web/dist/index.html')), '先构建共用 web 前端');
  }
  if (process.argv.includes('--require-lock')) {
    assert.ok(existsSync(resolve(root, 'src-tauri/Cargo.lock')), '发布前必须生成并审查 Cargo.lock');
  }
  console.log('桌面配置静态检查通过；此检查不能替代 Rust 编译、网络集成与真机验收。');
}
