import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { NativeTranslationApi, normalizeBackendOrigin } from './nativeApi';

const sessionId = '1d07a5a3-b9e7-4d9d-a92c-90634b71b0e6';
const requestId = 'cf92c606-ff53-45b0-93f8-9f9d158d6df0';
const jobId = '504f7193-56f0-4517-ae82-52ac245439b2';
const expiresAt = '2099-01-01T00:00:00+00:00';
const auth = {
  device_id: '68c1c4f4-a66a-4d5c-a1d8-253a7176f61e',
  device_name: '译境文字宠物',
  expires_at: expiresAt,
  auth_mode: 'bearer',
  csrf_token: null,
};
const backend = {
  origin: 'http://127.0.0.1:8765',
  paired: false,
  generation: 1,
  shortcut_available: false,
};
const request = {
  text: 'Hello',
  target_language: 'zh-Hans',
  source_language: 'auto',
  style: 'standard' as const,
  domain: 'general' as const,
  task_mode: 'auto' as const,
};
const work = { session_id: sessionId, generation: 0, expires_at: expiresAt };
const running = {
  job_id: jobId,
  session_id: sessionId,
  client_request_id: requestId,
  generation: 1,
  status: 'running',
  created_at: '2026-09-10T00:00:00+00:00',
  expires_at: expiresAt,
  result: null,
  error: null,
};

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('受控原生传输适配器', () => {
  it('读取本机桥状态，不自动设置 origin、不调用 fetch 或存储凭据', async () => {
    const bridge = vi.fn().mockResolvedValue(backend);
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    await expect(new NativeTranslationApi(bridge).backendStatus()).resolves.toEqual(backend);
    expect(bridge).toHaveBeenCalledExactlyOnceWith('backend_status', undefined);
    expect(fetcher).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
  });

  it('只有明确的 configureBackend 调用才发送配置命令', async () => {
    const bridge = vi.fn().mockResolvedValue({
      ...backend,
      origin: 'https://private.example',
      generation: 2,
    });
    const api = new NativeTranslationApi(bridge);
    await expect(api.configureBackend(' https://private.example/ ')).resolves.toMatchObject({
      origin: 'https://private.example',
      generation: 2,
    });
    expect(bridge).toHaveBeenCalledExactlyOnceWith('configure_backend', {
      origin: 'https://private.example',
    });
  });

  it.each([
    'http://192.168.1.2:8765',
    'http://127.1:8765',
    'http://2130706433:8765',
    'http://127.0.0.1',
    'http://localhost:1023',
    'http://localhost:65536',
    'https://user:secret@example.com',
    'https://example.com/api',
    'https://example.com?code=secret',
    'https://example.com#token',
    'https://exa mple.com',
    'https://example.com/%2e',
    'https://example.com/.',
    'file:///C:/private.txt',
    'javascript:alert(1)',
    '',
  ])('拒绝不符合桌面边界的 origin：%s', async (origin) => {
    const bridge = vi.fn();
    await expect(new NativeTranslationApi(bridge).configureBackend(origin)).rejects.toMatchObject({
      problem: { code: 'INVALID_ORIGIN' },
    });
    expect(bridge).not.toHaveBeenCalled();
  });

  it('允许显式本机端口与 HTTPS 源，不把路径拼接能力暴露给调用者', () => {
    expect(normalizeBackendOrigin('http://localhost:8765/')).toBe('http://localhost:8765');
    expect(normalizeBackendOrigin('https://private.example:8443/')).toBe(
      'https://private.example:8443',
    );
  });

  it('配对只发送配对操作和码，认证方式由 Rust 固定为 Bearer，JS 只接收公开 AuthView', async () => {
    const bridge = vi.fn().mockResolvedValue({ status: 201, body: auth });
    const result = await new NativeTranslationApi(bridge).pair('ABCD2345EFGH');
    expect(bridge).toHaveBeenCalledExactlyOnceWith('api_request', {
      request: {
        operation: 'pair',
        code: 'ABCD2345EFGH',
        device_name: '译境文字宠物',
      },
    });
    expect(result).toEqual(auth);
    expect(result).not.toHaveProperty('access_token');
    expect(result).not.toHaveProperty('token_type');
  });

  it.each([
    { ...auth, access_token: 'must-never-reach-react' },
    { ...auth, access_token: null },
    { ...auth, token_type: 'Bearer' },
    { ...auth, auth_mode: 'cookie', csrf_token: 'csrf' },
    { ...auth, csrf_token: 'unexpected-csrf' },
    { ...auth, expires_at: 'not-a-date' },
    { ...auth, device_id: '' },
  ])('拒绝错误认证模式、令牌泄漏或损坏认证视图', async (body) => {
    const bridge = vi.fn().mockResolvedValue({ status: 200, body });
    const error = await new NativeTranslationApi(bridge)
      .auth()
      .catch((failure: unknown) => failure);
    expect(error).toMatchObject({ problem: { code: 'INVALID_RESPONSE' } });
    expect(String(error)).not.toContain('must-never-reach-react');
  });

  it('复用工作会话解析器，并且不会把 CSRF 放进原生请求', async () => {
    const bridge = vi.fn().mockResolvedValue({ status: 201, body: work });
    await expect(new NativeTranslationApi(bridge).createSession(null)).resolves.toEqual(work);
    expect(bridge).toHaveBeenCalledExactlyOnceWith('api_request', {
      request: { operation: 'create_session' },
    });
  });

  it('翻译请求只按桥约定发送 snake_case 字段，返回已验证的同一请求', async () => {
    const bridge = vi.fn().mockResolvedValue({ status: 202, body: running });
    await expect(
      new NativeTranslationApi(bridge).translate(sessionId, requestId, request, null),
    ).resolves.toEqual(running);
    expect(bridge).toHaveBeenCalledExactlyOnceWith('api_request', {
      request: {
        operation: 'translate',
        session_id: sessionId,
        client_request_id: requestId,
        request,
      },
    });
  });

  it.each([
    { ...running, session_id: 'different-session' },
    { ...running, client_request_id: 'different-request' },
    { ...running, status: 'succeeded', result: null },
    { ...running, generation: -1 },
  ])('拒绝串单或无法验证的翻译任务', async (body) => {
    const bridge = vi.fn().mockResolvedValue({ status: 202, body });
    await expect(
      new NativeTranslationApi(bridge).translate(sessionId, requestId, request, null),
    ).rejects.toMatchObject({ problem: { code: 'INVALID_RESPONSE' } });
  });

  it('轮询与停止使用固定命令；停止的终态仍由共享 hook 判断', async () => {
    const bridge = vi
      .fn()
      .mockResolvedValueOnce({ status: 200, body: running })
      .mockResolvedValueOnce({
        status: 200,
        body: { ...running, status: 'cancelled' },
      });
    const api = new NativeTranslationApi(bridge);
    await expect(api.job(jobId)).resolves.toEqual(running);
    await expect(api.cancel(jobId, null)).resolves.toMatchObject({
      status: 'cancelled',
    });
    expect(bridge.mock.calls).toEqual([
      ['api_request', { request: { operation: 'job', job_id: jobId } }],
      ['api_request', { request: { operation: 'cancel', job_id: jobId } }],
    ]);
  });

  it.each(['job', 'cancel'] as const)('拒绝 %s 返回另一个任务 ID', async (operation) => {
    const bridge = vi.fn().mockResolvedValue({
      status: 200,
      body: { ...running, job_id: 'wrong-job' },
    });
    const api = new NativeTranslationApi(bridge);
    const result = operation === 'job' ? api.job(jobId) : api.cancel(jobId, null);
    await expect(result).rejects.toMatchObject({
      problem: { code: 'INVALID_RESPONSE' },
    });
  });

  it('退出和清空只接收准确的 204/null；不接受伪造成功正文', async () => {
    const bridge = vi
      .fn()
      .mockResolvedValueOnce({ status: 204, body: null })
      .mockResolvedValueOnce({ status: 204, body: null })
      .mockResolvedValueOnce({ status: 200, body: { ok: true } });
    const api = new NativeTranslationApi(bridge);
    await expect(api.logout(null)).resolves.toBeUndefined();
    await expect(api.deleteSession(sessionId, null)).resolves.toBeUndefined();
    await expect(api.logout(null)).rejects.toMatchObject({
      problem: { code: 'INVALID_RESPONSE' },
    });
  });

  it('已取消的信号不得再发起桥请求', async () => {
    const bridge = vi.fn();
    const controller = new AbortController();
    controller.abort();
    await expect(new NativeTranslationApi(bridge).auth(controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    });
    expect(bridge).not.toHaveBeenCalled();
  });

  it('在派发微任务前取消，同样不会启动 Rust 请求', async () => {
    const bridge = vi.fn();
    const controller = new AbortController();
    const result = new NativeTranslationApi(bridge).auth(controller.signal);
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(bridge).not.toHaveBeenCalled();
  });

  it('翻译中 abort 仅丢弃迟到桥响应，停止仍需发送已有 cancel 操作', async () => {
    let finishBridge!: (value: unknown) => void;
    const bridge = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishBridge = resolve;
          }),
      )
      .mockResolvedValueOnce({
        status: 200,
        body: { ...running, status: 'cancelled' },
      });
    const api = new NativeTranslationApi(bridge);
    const controller = new AbortController();
    const pending = api.job(jobId, controller.signal);
    await Promise.resolve();
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    finishBridge({ status: 200, body: running });
    await Promise.resolve();
    expect(bridge).toHaveBeenCalledTimes(1);
    await expect(api.cancel(jobId, null)).resolves.toMatchObject({
      status: 'cancelled',
    });
    expect(bridge).toHaveBeenCalledTimes(2);
  });

  it('桥接等待超时保留 NETWORK_UNCONFIRMED，不声称请求被撤回', async () => {
    vi.useFakeTimers();
    const bridge = vi.fn().mockImplementation(() => new Promise(() => undefined));
    const result = new NativeTranslationApi(bridge)
      .translate(sessionId, requestId, request, null)
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(await result).toMatchObject({
      status: 0,
      problem: { code: 'NETWORK_UNCONFIRMED', retryable: true },
    });
    expect(bridge).toHaveBeenCalledTimes(1);
  });

  it('原生断流错误不降级成确定拒绝，也不把内部报错原文回显', async () => {
    const bridge = vi.fn().mockRejectedValue({
      code: 'NETWORK_UNCONFIRMED',
      message: 'private text and Bearer secret',
      status: 0,
      retryable: true,
    });
    const error = await new NativeTranslationApi(bridge)
      .translate(sessionId, requestId, request, null)
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 0,
      problem: { code: 'NETWORK_UNCONFIRMED', retryable: true },
    });
    expect(String(error)).not.toContain('Bearer secret');
  });

  it('保留可信的 HTTP 状态以便共享 hook 识别配对过期', async () => {
    const bridge = vi.fn().mockRejectedValue({
      code: 'PAIRING_REQUIRED',
      message: 'untrusted extra text',
      status: 401,
      retryable: false,
    });
    await expect(new NativeTranslationApi(bridge).auth()).rejects.toMatchObject({
      status: 401,
      problem: { code: 'PAIRING_REQUIRED', retryable: false },
    });
  });

  it('未知异常不回显详情，并谨慎保留状态未确认', async () => {
    const bridge = vi.fn().mockRejectedValue('secret debug value');
    const error = await new NativeTranslationApi(bridge)
      .auth()
      .catch((failure: unknown) => failure);
    expect(error).toMatchObject({ problem: { code: 'NETWORK_UNCONFIRMED' } });
    expect(String(error)).not.toContain('secret debug');
  });

  it('未知错误附带 422 也不能被认定为确定拒绝', async () => {
    const bridge = vi.fn().mockRejectedValue({
      code: 'UNKNOWN_BRIDGE_ERROR',
      status: 422,
      message: 'private details',
    });
    await expect(
      new NativeTranslationApi(bridge).translate(sessionId, requestId, request, null),
    ).rejects.toMatchObject({
      status: 0,
      problem: { code: 'NETWORK_UNCONFIRMED' },
    });
  });

  it('读取窗口状态时拒绝畸形 generation 和 origin', async () => {
    const bridge = vi
      .fn()
      .mockResolvedValueOnce({ ...backend, generation: -1 })
      .mockResolvedValueOnce({ ...backend, origin: 'http://192.168.1.2:8765' });
    const api = new NativeTranslationApi(bridge);
    await expect(api.backendStatus()).rejects.toMatchObject({
      problem: { code: 'INVALID_RESPONSE' },
    });
    await expect(api.backendStatus()).rejects.toMatchObject({
      problem: { code: 'INVALID_RESPONSE' },
    });
  });

  it('健康检查仅接受约定的 API 版本', async () => {
    const bridge = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        body: { status: 'ok', api_version: '1' },
      })
      .mockResolvedValueOnce({
        status: 200,
        body: { status: 'ok', api_version: '2' },
      });
    const api = new NativeTranslationApi(bridge);
    await expect(api.health()).resolves.toEqual({
      status: 'ok',
      api_version: '1',
    });
    await expect(api.health()).rejects.toMatchObject({
      problem: { code: 'INVALID_RESPONSE' },
    });
  });

  it('页面离开只尽力清理已有会话，失败不会启动重试循环', async () => {
    const bridge = vi.fn().mockRejectedValue({
      code: 'NETWORK_UNCONFIRMED',
      status: 0,
      retryable: true,
    });
    new NativeTranslationApi(bridge).leaveSession(sessionId, null);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(bridge).toHaveBeenCalledExactlyOnceWith('api_request', {
      request: { operation: 'delete_session', session_id: sessionId },
    });
  });
});
