import assert from 'node:assert/strict';
import test from 'node:test';
import { validateConfiguration, readConfiguration } from './verify-config.mjs';

test('现有配置遵守最小授权', () => validateConfiguration(...readConfiguration()));
for (const [name, mutate] of [
  ['拒绝官方Schema未定义属性', (parts) => { parts[0].app.windows[0].imaginaryOption = true; }],
  ['拒绝远端前端', (parts) => { parts[0].build.devUrl = 'https://example.test'; }],
  ['拒绝自动创建无拦截窗口', (parts) => { parts[0].app.windows[0].create = true; }],
  ['拒绝新增窗口', (parts) => { parts[0].app.windows.push({ label: 'other' }); }],
  ['拒绝暴露全局API', (parts) => { parts[0].app.withGlobalTauri = true; }],
  ['拒绝关闭隐私模式', (parts) => { parts[0].app.windows[0].incognito = false; }],
  ['拒绝宽泛网络CSP', (parts) => { parts[0].app.security.csp += '; connect-src *'; }],
  ['拒绝脚本eval', (parts) => { parts[0].app.security.csp += "; script-src 'unsafe-eval'"; }],
  ['拒绝内联样式', (parts) => { parts[0].app.security.csp = parts[0].app.security.csp.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'"); }],
  ['拒绝远端能力', (parts) => { parts[1].remote = { urls: ['https://example.test'] }; }],
  ['拒绝Shell能力', (parts) => { parts[1].permissions.push('shell:default'); }],
  ['拒绝移除重定向限制', (parts) => { parts[4] = parts[4].replace('redirect::Policy::none()', 'redirect::Policy::limited(10)'); }],
  ['拒绝移除代理限制', (parts) => { parts[4] = parts[4].replace('.no_proxy()', ''); }],
  ['拒绝移除导航保护', (parts) => { parts[3] = parts[3].replace('.on_navigation(bridge::local_navigation_allowed)', ''); }],
  ['拒绝退出前遗漏命令门禁', (parts) => { parts[3] = parts[3].replace('if app.state::<HostState>().begin_exit()', 'if true'); }],
  ['拒绝退出前遗漏远端撤销', (parts) => { parts[3] = parts[3].replace('state.bridge.request(ApiRequest::Logout).await', ''); }],
  ['拒绝移除撤销超时', (parts) => { parts[4] = parts[4].replace('outgoing.timeout(Duration::from_secs(3))', 'outgoing'); }],
  ['拒绝失败后遗失可重试撤销凭据', (parts) => { parts[4] = parts[4].replace('self.pending_logout = token.clone()', 'self.pending_logout = None'); }],
  ['拒绝将响应流中断误报为JSON错误', (parts) => { parts[4] = parts[4].replace('response.chunk().await.map_err(|_| BridgeError::network())?', 'response.chunk().await.map_err(|_| BridgeError::invalid_response())?'); }],
]) {
  test(name, () => {
    const parts = readConfiguration();
    mutate(parts);
    assert.throws(() => validateConfiguration(...parts));
  });
}
