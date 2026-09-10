import { describe, expect, it, vi } from 'vitest';
import { ApiError, jobResponse, TranslationApi } from './api';
import { isStaticRequest } from './service-worker.js';

const translationRequest = {
  text: 'Hello',
  target_language: 'zh-Hans',
  source_language: 'auto',
  style: 'standard' as const,
  domain: 'general' as const,
  task_mode: 'auto' as const,
};
const runningJob = {
  job_id: 'job-1',
  session_id: 'session-1',
  client_request_id: 'request-1',
  generation: 1,
  status: 'running',
  created_at: '2026-09-07',
  expires_at: '2099-01-01',
  result: null,
  error: null,
};

describe('任务响应绑定', () => {
  it.each(['session_id', 'client_request_id'] as const)(
    '提交响应的 %s 不匹配时拒绝绑定到另一轮',
    async (field) => {
      const fetcher = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ ...runningJob, [field]: 'other-request' }), {
            status: 202,
          }),
        );
      vi.stubGlobal('fetch', fetcher);
      await expect(
        new TranslationApi().translate('session-1', 'request-1', translationRequest, 'csrf'),
      ).rejects.toMatchObject({ problem: { code: 'INVALID_RESPONSE', retryable: true } });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['job', 'cancel'] as const)('%s 响应属于另一任务编号时不接受其状态', async (method) => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ ...runningJob, job_id: 'other-job', status: 'cancelled' })),
        ),
    );
    const api = new TranslationApi();
    await expect(
      method === 'job' ? api.job('job-1') : api.cancel('job-1', 'csrf'),
    ).rejects.toMatchObject({ problem: { code: 'INVALID_RESPONSE', retryable: true } });
  });

  it('共享校验器拒绝同一任务编号下被替换的代次', () => {
    expect(() => jobResponse(runningJob, { job_id: 'job-1', generation: 2 })).toThrow(
      '任务与本轮不匹配',
    );
  });

  it('共享校验器接受全部身份一致的任务并保留可选绑定调用', () => {
    expect(
      jobResponse(runningJob, {
        job_id: 'job-1',
        session_id: 'session-1',
        client_request_id: 'request-1',
        generation: 1,
      }),
    ).toBe(runningJob);
    expect(jobResponse(runningJob)).toBe(runningJob);
  });
});

describe('HTTP 与离线隐私边界', () => {
  it('仅使用同源 Cookie，写操作带内存 CSRF，禁止缓存和重定向', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ session_id: 's', generation: 0 }), { status: 200 }),
      );
    vi.stubGlobal('fetch', fetcher);
    const api = new TranslationApi();
    await api.createSession('csrf-only-memory');
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/sessions',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        cache: 'no-store',
        redirect: 'error',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRF-Token': 'csrf-only-memory',
        },
        body: '{}',
      }),
    );
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
  it('配对使用 cookie 模式且不把配对码放入 URL', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          device_id: 'd',
          device_name: 'browser',
          expires_at: '2099-01-01',
          auth_mode: 'cookie',
          csrf_token: 'csrf',
          access_token: null,
          token_type: null,
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', fetcher);
    await new TranslationApi().pair('ABCDEFGHIJKL');
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/pair/exchange');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      code: 'ABCDEFGHIJKL',
      device_name: '译境网页',
      auth_mode: 'cookie',
    });
  });
  it('非 JSON 失败响应不会把服务器 HTML 放入界面', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<h1>private stacktrace</h1>', { status: 500 })),
    );
    await expect(new TranslationApi().auth()).rejects.toMatchObject({
      status: 500,
      problem: { code: 'HTTP_ERROR' },
    });
  });
  it('无连接时明确请求状态未确认，不声称服务器已经停止', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection closed')));
    await expect(new TranslationApi().auth()).rejects.toBeInstanceOf(ApiError);
    await expect(new TranslationApi().auth()).rejects.toMatchObject({
      problem: { code: 'NETWORK_UNCONFIRMED' },
    });
  });
  it('已收到 202 后响应体断流仍报告提交状态未确认，不包装成成功或确定拒绝', async () => {
    const response = new Response('', { status: 202 });
    vi.spyOn(response, 'text').mockRejectedValue(new TypeError('private response stream failure'));
    const fetcher = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetcher);
    const failure = await new TranslationApi()
      .translate('session-1', 'request-1', translationRequest, 'csrf')
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 0,
      problem: { code: 'NETWORK_UNCONFIRMED', retryable: true },
    });
    expect((failure as ApiError).message).toContain('请求状态尚未确认');
    expect((failure as ApiError).message).not.toContain('private response');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each(['{broken-json', 'null', '[]'])(
    '202 返回畸形或非对象 JSON %s 时不认定任务结束',
    async (body) => {
      const fetcher = vi.fn().mockResolvedValue(new Response(body, { status: 202 }));
      vi.stubGlobal('fetch', fetcher);
      await expect(
        new TranslationApi().translate('session-1', 'request-1', translationRequest, 'csrf'),
      ).rejects.toMatchObject({
        status: 202,
        problem: { code: 'INVALID_RESPONSE', retryable: true },
      });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it.each([
    ['缺少任务 ID', { ...runningJob, job_id: '' }],
    ['未知任务状态', { ...runningJob, status: 'completed' }],
    ['成功状态缺少结果', { ...runningJob, status: 'succeeded' }],
    ['终态错误结构损坏', { ...runningJob, status: 'failed', error: { message: 'incomplete' } }],
  ])('拒绝 202 的无效 Job：%s', async (_label, payload) => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(payload), { status: 202 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(
      new TranslationApi().translate('session-1', 'request-1', translationRequest, 'csrf'),
    ).rejects.toMatchObject({ problem: { code: 'INVALID_RESPONSE', retryable: true } });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('保留可确认的提交 422 状态，供界面与未知提交区分', async () => {
    const problem = {
      code: 'INVALID_REQUEST',
      message: '原文不符合限制',
      retryable: false,
      request_id: 'trace-1',
    };
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ error: problem }), { status: 422 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(
      new TranslationApi().translate('session-1', 'request-1', translationRequest, 'csrf'),
    ).rejects.toMatchObject({ status: 422, problem });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('拒绝在网页中接收 Bearer 或空 CSRF 的认证模式', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ auth_mode: 'bearer', csrf_token: null, device_id: 'd' }), {
          status: 200,
        }),
      ),
    );
    await expect(new TranslationApi().auth()).rejects.toMatchObject({
      problem: { code: 'AUTH_MODE_MISMATCH' },
    });
  });
  it('页面关闭清理使用 Cookie、CSRF、keepalive 而不使用 sendBeacon', () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    new TranslationApi().leaveSession('session-1', 'csrf');
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/sessions/session-1',
      expect.objectContaining({
        method: 'DELETE',
        keepalive: true,
        credentials: 'include',
        headers: { 'X-CSRF-Token': 'csrf' },
      }),
    );
  });
  it('SW 仅处理白名单 GET 静态资产，不处理 API/跨域/查询或写请求', () => {
    const origin = 'https://private.example';
    const allowed = ['/index.html', '/assets/app.js', '/pet-icon.svg'];
    const request = (path: string, method = 'GET', mode = 'cors') => ({
      url: `${origin}${path}`,
      method,
      mode,
    });
    expect(isStaticRequest(request('/assets/app.js'), origin, allowed)).toBe(true);
    expect(isStaticRequest(request('/', 'GET', 'navigate'), origin, allowed)).toBe(true);
    expect(
      isStaticRequest(request('/api/v1/auth/session'), origin, [
        ...allowed,
        '/api/v1/auth/session',
      ]),
    ).toBe(false);
    expect(isStaticRequest(request('/api'), origin, ['/api'])).toBe(false);
    expect(isStaticRequest(request('/assets/app.js?token=secret'), origin, allowed)).toBe(false);
    expect(isStaticRequest(request('/assets/app.js', 'POST'), origin, allowed)).toBe(false);
    expect(
      isStaticRequest(
        { url: 'https://other.example/assets/app.js', method: 'GET', mode: 'cors' },
        origin,
        allowed,
      ),
    ).toBe(false);
    expect(isStaticRequest(request('/private-recording.wav'), origin, allowed)).toBe(false);
  });
});
