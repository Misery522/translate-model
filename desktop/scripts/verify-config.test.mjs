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
  ['拒绝增大最小宽度', (parts) => { parts[0].app.windows[0].minWidth = 400; }],
  ['拒绝减小最小高度', (parts) => { parts[0].app.windows[0].minHeight = 300; }],
  ['拒绝初始尺寸小于最小尺寸', (parts) => { parts[0].app.windows[0].width = 299; }],
  ['拒绝关闭窗口缩放', (parts) => { parts[0].app.windows[0].resizable = false; }],
  ['拒绝关闭窗口置顶', (parts) => { parts[0].app.windows[0].alwaysOnTop = false; }],
  ['拒绝在任务栏显示宠物', (parts) => { parts[0].app.windows[0].skipTaskbar = false; }],
  ['拒绝恢复系统边框', (parts) => { parts[0].app.windows[0].decorations = true; }],
  ['拒绝透明宿主窗口', (parts) => { parts[0].app.windows[0].transparent = true; }],
  ['拒绝关闭安装包配置', (parts) => { parts[0].bundle.active = false; }],
  ['拒绝非 NSIS 安装目标', (parts) => { parts[0].bundle.targets = ['msi']; }],
  ['拒绝扩大安装包图标范围', (parts) => { parts[0].bundle.icon.push('icons/extra.png'); }],
  ['拒绝更改 WebView2 引导方式', (parts) => { parts[0].bundle.windows.webviewInstallMode.type = 'skip'; }],
  ['拒绝显示 WebView2 引导安装', (parts) => { parts[0].bundle.windows.webviewInstallMode.silent = false; }],
  ['拒绝宠物样式宽于宿主最小宽度', (parts) => { parts[5] = parts[5].replace('min-width: 280px', 'min-width: 320px'); }],
  ['拒绝宽泛网络CSP', (parts) => { parts[0].app.security.csp += '; connect-src *'; }],
  ['拒绝脚本eval', (parts) => { parts[0].app.security.csp += "; script-src 'unsafe-eval'"; }],
  ['拒绝内联样式', (parts) => { parts[0].app.security.csp = parts[0].app.security.csp.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'"); }],
  ['拒绝远端能力', (parts) => { parts[1].remote = { urls: ['https://example.test'] }; }],
  ['拒绝Shell能力', (parts) => { parts[1].permissions.push('shell:default'); }],
  ['拒绝移除重定向限制', (parts) => { parts[4] = parts[4].replace('redirect::Policy::none()', 'redirect::Policy::limited(10)'); }],
  ['拒绝移除代理限制', (parts) => { parts[4] = parts[4].replace('.no_proxy()', ''); }],
  ['拒绝移除导航保护', (parts) => { parts[3] = parts[3].replace('bridge::local_navigation_allowed(url, dev_origin.as_ref())', 'true'); }],
  ['拒绝放宽开发导航来源', (parts) => { parts[4] = parts[4].replace('url.origin() == origin.origin()', 'true'); }],
  ['拒绝放宽开发宠物入口', (parts) => { parts[4] = parts[4].replace('url.query() == Some("view=pet")', 'true'); }],
  ['拒绝退出前遗漏命令门禁', (parts) => { parts[3] = parts[3].replace('if app.state::<HostState>().begin_exit()', 'if true'); }],
  ['拒绝更改托盘菜单标签', (parts) => { parts[3] = parts[3].replace('"打开译境"', '"打开"'); }],
  ['拒绝左键直接弹出菜单', (parts) => { parts[3] = parts[3].replace('.show_menu_on_left_click(false)', '.show_menu_on_left_click(true)'); }],
  ['拒绝绕过托盘菜单路由', (parts) => { parts[3] = parts[3].replace('match tray_action(event.id.as_ref())', 'match TrayAction::Ignore'); }],
  ['拒绝绕过托盘点击筛选', (parts) => { parts[3] = parts[3].replace('if tray_click_shows(button, button_state)', 'if true'); }],
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
