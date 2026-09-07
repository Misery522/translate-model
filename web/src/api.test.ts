import { describe, expect, it, vi } from 'vitest';
import { ApiError, TranslationApi } from './api';
import { isStaticRequest } from './service-worker.js';

describe('HTTP 与离线隐私边界', () => {
  it('仅使用同源 Cookie，写操作带内存 CSRF，禁止缓存和重定向', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ session_id: 's', generation: 0 }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const api = new TranslationApi();
    await api.createSession('csrf-only-memory');
    expect(fetcher).toHaveBeenCalledWith('/api/v1/sessions', expect.objectContaining({ method: 'POST', credentials: 'include', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-only-memory' }, body: '{}' }));
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
  it('配对使用 cookie 模式且不把配对码放入 URL', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ device_id: 'd', device_name: 'browser', expires_at: '2099-01-01', auth_mode: 'cookie', csrf_token: 'csrf', access_token: null, token_type: null }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await new TranslationApi().pair('ABCDEFGHIJKL');
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/pair/exchange');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ code: 'ABCDEFGHIJKL', device_name: '译境网页', auth_mode: 'cookie' });
  });
  it('非 JSON 失败响应不会把服务器 HTML 放入界面', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<h1>private stacktrace</h1>', { status: 500 })));
    await expect(new TranslationApi().auth()).rejects.toMatchObject({ status: 500, problem: { code: 'HTTP_ERROR' } });
  });
  it('无连接时明确请求状态未确认，不声称服务器已经停止', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection closed')));
    await expect(new TranslationApi().auth()).rejects.toBeInstanceOf(ApiError);
    await expect(new TranslationApi().auth()).rejects.toMatchObject({ problem: { code: 'NETWORK_UNCONFIRMED' } });
  });
  it('拒绝在网页中接收 Bearer 或空 CSRF 的认证模式', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ auth_mode: 'bearer', csrf_token: null, device_id: 'd' }), { status: 200 })));
    await expect(new TranslationApi().auth()).rejects.toMatchObject({ problem: { code: 'AUTH_MODE_MISMATCH' } });
  });
  it('页面关闭清理使用 Cookie、CSRF、keepalive 而不使用 sendBeacon', () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    new TranslationApi().leaveSession('session-1', 'csrf');
    expect(fetcher).toHaveBeenCalledWith('/api/v1/sessions/session-1', expect.objectContaining({ method: 'DELETE', keepalive: true, credentials: 'include', headers: { 'X-CSRF-Token': 'csrf' } }));
  });
  it('SW 仅处理白名单 GET 静态资产，不处理 API/跨域/查询或写请求', () => {
    const origin = 'https://private.example';
    const allowed = ['/index.html', '/assets/app.js', '/pet-icon.svg'];
    const request = (path: string, method = 'GET', mode = 'cors') => ({ url: `${origin}${path}`, method, mode });
    expect(isStaticRequest(request('/assets/app.js'), origin, allowed)).toBe(true);
    expect(isStaticRequest(request('/', 'GET', 'navigate'), origin, allowed)).toBe(true);
    expect(isStaticRequest(request('/api/v1/auth/session'), origin, [...allowed, '/api/v1/auth/session'])).toBe(false);
    expect(isStaticRequest(request('/api'), origin, ['/api'])).toBe(false);
    expect(isStaticRequest(request('/assets/app.js?token=secret'), origin, allowed)).toBe(false);
    expect(isStaticRequest(request('/assets/app.js', 'POST'), origin, allowed)).toBe(false);
    expect(isStaticRequest({ url: 'https://other.example/assets/app.js', method: 'GET', mode: 'cors' }, origin, allowed)).toBe(false);
    expect(isStaticRequest(request('/private-recording.wav'), origin, allowed)).toBe(false);
  });
});
