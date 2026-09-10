import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { ApiError, TranslationApi } from './api';
import type { AgentResult, Job, TranslationRequest } from './types';
import { characterCount, useTranslator } from './useTranslator';

const auth = {
  device_id: 'device-1',
  device_name: '测试设备',
  auth_mode: 'cookie' as const,
  expires_at: '2099-01-01',
  csrf_token: 'csrf-memory-only',
};
const request: TranslationRequest = {
  text: 'Hello',
  target_language: 'zh-Hans',
  source_language: 'auto',
  style: 'standard',
  domain: 'general',
  task_mode: 'auto',
};
const result: AgentResult = {
  route: 'translate_text',
  detected_language: 'en',
  detection_status: 'detected',
  preserved_source: 'Hello',
  translated_text: '你好',
  annotated_copy: null,
  annotations: [],
  applied_terms: [],
  warnings: [],
  elapsed_ms: 1200,
};
type SubmittedIdentity = Pick<Job, 'session_id' | 'client_request_id'>;

function job(text = '你好', status: Job['status'] = 'succeeded', identity: Partial<Job> = {}): Job {
  return {
    job_id: 'job-1',
    session_id: 'session-1',
    client_request_id: 'request-1',
    generation: 1,
    status,
    created_at: '2026-09-07',
    expires_at: '2099-01-01',
    result: status === 'succeeded' ? { ...result, translated_text: text } : null,
    error: null,
    ...identity,
  };
}
function submittedJob(
  api: TranslationApi,
  text = '你好',
  status: Job['status'] = 'succeeded',
): Job {
  const [session_id, client_request_id] = vi.mocked(api.translate).mock.calls.at(-1)!;
  return job(text, status, { session_id, client_request_id });
}
function fixture() {
  const api = new TranslationApi();
  vi.spyOn(api, 'auth').mockResolvedValue(auth);
  vi.spyOn(api, 'pair').mockResolvedValue(auth);
  let sequence = 0;
  vi.spyOn(api, 'createSession').mockImplementation(async () => ({
    session_id: `session-${++sequence}`,
    generation: 0,
    expires_at: '2099-01-01',
  }));
  vi.spyOn(api, 'deleteSession').mockResolvedValue();
  vi.spyOn(api, 'logout').mockResolvedValue();
  vi.spyOn(api, 'translate').mockImplementation(async () => submittedJob(api));
  vi.spyOn(api, 'job').mockImplementation(async () => submittedJob(api));
  vi.spyOn(api, 'cancel').mockImplementation(async () => submittedJob(api, '', 'cancelled'));
  return api;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function ready(api: TranslationApi) {
  render(<App api={api} />);
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已连接'));
}
function enter(text = 'Hello') {
  fireEvent.change(screen.getByLabelText('原文'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /开始翻译/ }));
}

// 仅替换网络边界，保留真实 TranslationApi 的读取、解析与运行时校验链路。
function httpFixture(
  submit: (identity: SubmittedIdentity) => Response | Promise<Response>,
  poll: (identity: SubmittedIdentity) => Response | Promise<Response> = (identity) =>
    new Response(JSON.stringify(job('你好', 'succeeded', identity))),
  cancelResponse: (identity: SubmittedIdentity) => Response | Promise<Response> = (identity) =>
    new Response(JSON.stringify(job('', 'cancelled', identity))),
) {
  let sequence = 0;
  let identity: SubmittedIdentity;
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/auth/session' && method === 'GET')
      return new Response(JSON.stringify(auth));
    if (path === '/api/v1/sessions' && method === 'POST')
      return new Response(
        JSON.stringify({
          session_id: `session-${++sequence}`,
          generation: 0,
          expires_at: '2099-01-01',
        }),
        { status: 201 },
      );
    if (path.startsWith('/api/v1/sessions/') && method === 'DELETE')
      return new Response(null, { status: 204 });
    if (path === '/api/v1/translations' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as SubmittedIdentity;
      identity = { session_id: body.session_id, client_request_id: body.client_request_id };
      return submit(identity);
    }
    if (path === '/api/v1/translations/job-1' && method === 'GET') return poll(identity);
    if (path === '/api/v1/translations/job-1/cancel' && method === 'POST')
      return cancelResponse(identity);
    throw new Error(`测试未声明的 HTTP 请求：${method} ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
  const calls = (method: string, path: string) =>
    fetcher.mock.calls.filter(
      ([url, init]) => String(url) === path && (init?.method ?? 'GET') === method,
    );
  return { api: new TranslationApi(), calls };
}

describe('真实 HTTP 响应到会话状态的回归', () => {
  it.each([
    [
      '202 响应体断流',
      () => {
        const response = new Response('', { status: 202 });
        vi.spyOn(response, 'text').mockRejectedValue(new TypeError('connection closed'));
        return response;
      },
    ],
    ['202 畸形 JSON', () => new Response('{broken-json', { status: 202 })],
    [
      '202 无效 Job',
      () => new Response(JSON.stringify({ ...job(), result: null }), { status: 202 }),
    ],
  ])('%s 后不重投、保留取消与清空入口，并可删除未知任务所属会话', async (_label, response) => {
    const { api, calls } = httpFixture(response);
    await ready(api);
    enter('不能自动重投的原文');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('任务状态尚未确认'));
    expect(screen.getByRole('button', { name: /停止此轮/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: '清空' })).toBeEnabled();
    expect(screen.getByRole('button', { name: /重试此轮/ })).toBeDisabled();
    fireEvent(window, new Event('online'));
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '另一个请求' } });
    fireEvent.keyDown(screen.getByLabelText('原文'), { key: 'Enter', ctrlKey: true });
    fireEvent.submit(screen.getByLabelText('原文').closest('form')!);
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /停止此轮/ }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已停止接收'));
    expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(1);
    expect(calls('POST', '/api/v1/sessions')).toHaveLength(2);
    expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(0);
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /停止此轮/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /开始翻译/ })).toBeEnabled();
  });

  it('未知提交可直接清空：删除原会话后恢复空白，不重新发送原文', async () => {
    const { api, calls } = httpFixture(() => new Response('{broken-json', { status: 202 }));
    await ready(api);
    enter('清空后不可恢复的原文');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('任务状态尚未确认'));
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('等待翻译'));
    expect(screen.queryByLabelText('一轮翻译')).not.toBeInTheDocument();
    expect(screen.getByText('0 / 4000 字符')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /停止此轮/ })).not.toBeInTheDocument();
    expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(1);
    expect(calls('POST', '/api/v1/sessions')).toHaveLength(2);
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
  });

  it.each([400, 409, 422, 429])(
    '提交明确返回 HTTP %i 拒绝后允许手动重试，不保留未知任务取消标记',
    async (status) => {
      const { api, calls } = httpFixture(
        () =>
          new Response(
            JSON.stringify({
              error: {
                code: 'REQUEST_REJECTED',
                message: '本轮未被接受',
                retryable: true,
                request_id: 'trace-1',
              },
            }),
            { status },
          ),
      );
      await ready(api);
      enter();
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('本轮未被接受'));
      expect(screen.getByRole('status')).not.toHaveTextContent('任务状态尚未确认');
      expect(screen.queryByRole('button', { name: /停止此轮/ })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /重试此轮/ })).toBeEnabled();
      expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
      expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(0);
    },
  );

  it.each(['succeeded', 'failed', 'cancelled', 'timed_out'] as const)(
    '可信 %s 终态可以解除取消标记',
    async (status) => {
      const payload = {
        ...job('你好', status),
        error: ['failed', 'timed_out'].includes(status)
          ? {
              code: 'MODEL_FAILED',
              message: '本轮处理已结束',
              retryable: true,
              request_id: 'trace-1',
            }
          : null,
      };
      const { api, calls } = httpFixture(
        (identity) => new Response(JSON.stringify({ ...payload, ...identity }), { status: 202 }),
      );
      const { result: state } = renderHook(() => useTranslator(api));
      await waitFor(() => expect(state.current.busy).toBe(false));
      await act(async () => state.current.send(request));
      expect(state.current.canCancel).toBe(false);
      expect(state.current.busy).toBe(false);
      expect(state.current.notice).not.toContain('状态尚未确认');
      expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    },
  );

  it.each([
    [
      '读取响应体失败',
      () => {
        const response = new Response('');
        vi.spyOn(response, 'text').mockRejectedValue(new TypeError('connection closed'));
        return response;
      },
    ],
    ['畸形 JSON', () => new Response('{broken-json')],
    ['无效终态', () => new Response(JSON.stringify({ ...job(), status: 'unknown' }))],
    ['服务端 503', () => new Response('temporarily unavailable', { status: 503 })],
  ])('已接受任务在轮询%s后仍可精确取消，不重新提交', async (_label, poll) => {
    const { api, calls } = httpFixture(
      (identity) => new Response(JSON.stringify(job('', 'running', identity)), { status: 202 }),
      poll,
    );
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => {
      execution = state.current.send(request);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
      await execution;
    });
    expect(state.current.busy).toBe(false);
    expect(state.current.canCancel).toBe(true);
    expect(state.current.notice).toContain('任务状态尚未确认');
    await act(async () => state.current.send({ ...request, text: '禁止重投' }));
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    expect(calls('GET', '/api/v1/translations/job-1')).toHaveLength(1);
    await act(async () => state.current.cancel());
    expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(1);
    expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(0);
    expect(state.current.canCancel).toBe(false);
    expect(state.current.notice).toContain('已停止接收');
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
  });

  it.each(['queued', 'running'] as const)(
    '取消接口仍返回 %s 时不能声称取消已确认，允许再次取消同一任务',
    async (status) => {
      const cancelResponse = vi
        .fn()
        .mockImplementationOnce(
          (identity: SubmittedIdentity) => new Response(JSON.stringify(job('', status, identity))),
        )
        .mockImplementationOnce(
          (identity: SubmittedIdentity) =>
            new Response(JSON.stringify(job('', 'cancelled', identity))),
        );
      const { api, calls } = httpFixture(
        (identity) => new Response(JSON.stringify(job('', 'running', identity)), { status: 202 }),
        () => new Response('{broken-json'),
        cancelResponse,
      );
      const { result: state } = renderHook(() => useTranslator(api));
      await waitFor(() => expect(state.current.busy).toBe(false));
      vi.useFakeTimers();
      let execution!: Promise<void>;
      await act(async () => {
        execution = state.current.send(request);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(800);
        await execution;
      });
      await act(async () => state.current.cancel());
      expect(state.current.canCancel).toBe(true);
      expect(state.current.busy).toBe(false);
      expect(state.current.notice).toContain('未确认服务端停止');
      expect(state.current.notice).not.toContain('已停止接收此轮结果');
      await act(async () => state.current.cancel());
      expect(state.current.canCancel).toBe(false);
      expect(state.current.notice).toContain('已停止接收');
      expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(2);
      expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
      expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(0);
    },
  );
});

describe('本轮任务身份不可被响应替换', () => {
  it.each(['session_id', 'client_request_id'] as const)(
    '首次响应 %s 错绑时不显示旧译文，并通过原会话停止未知任务',
    async (field) => {
      const { api, calls } = httpFixture(
        (identity) =>
          new Response(
            JSON.stringify(
              job('另一轮旧译文', 'succeeded', { ...identity, [field]: 'another-turn' }),
            ),
            { status: 202 },
          ),
      );
      const { result: state } = renderHook(() => useTranslator(api));
      await waitFor(() => expect(state.current.busy).toBe(false));
      await act(async () => state.current.send(request));
      expect(state.current.canCancel).toBe(true);
      expect(state.current.notice).toContain('任务与本轮不匹配');
      expect(state.current.turns[0].result).toBeUndefined();
      await act(async () => state.current.send(request));
      expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
      await act(async () => state.current.cancel());
      expect(calls('DELETE', '/api/v1/sessions/session-1')).toHaveLength(1);
      expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(0);
      expect(state.current.canCancel).toBe(false);
    },
  );

  const mismatches: [string, Partial<Job>][] = [
    ['任务编号', { job_id: 'another-job' }],
    ['会话编号', { session_id: 'another-session' }],
    ['客户端请求编号', { client_request_id: 'another-request' }],
    ['任务代次', { generation: 2 }],
  ];

  it.each(mismatches)('轮询不能替换已接受任务的%s，仍向原任务取消', async (_label, mismatch) => {
    const { api, calls } = httpFixture(
      (identity) => new Response(JSON.stringify(job('', 'running', identity)), { status: 202 }),
      (identity) =>
        new Response(
          JSON.stringify(job('不能显示的旧结果', 'succeeded', { ...identity, ...mismatch })),
        ),
    );
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => {
      execution = state.current.send(request);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
      await execution;
    });
    expect(state.current.canCancel).toBe(true);
    expect(state.current.notice).toContain('任务与本轮不匹配');
    expect(state.current.turns[0].result).toBeUndefined();
    await act(async () => state.current.send(request));
    expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    await act(async () => state.current.cancel());
    expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(1);
    expect(calls('POST', '/api/v1/translations/another-job/cancel')).toHaveLength(0);
    expect(state.current.canCancel).toBe(false);
  });

  it.each(mismatches)(
    '取消响应%s错绑时保留取消入口，直到原任务终态确认',
    async (_label, mismatch) => {
      const cancelResponse = vi
        .fn()
        .mockImplementationOnce(
          (identity: SubmittedIdentity) =>
            new Response(JSON.stringify(job('', 'cancelled', { ...identity, ...mismatch }))),
        )
        .mockImplementationOnce(
          (identity: SubmittedIdentity) =>
            new Response(JSON.stringify(job('', 'cancelled', identity))),
        );
      const { api, calls } = httpFixture(
        (identity) => new Response(JSON.stringify(job('', 'running', identity)), { status: 202 }),
        () => new Response('{broken-json'),
        cancelResponse,
      );
      const { result: state } = renderHook(() => useTranslator(api));
      await waitFor(() => expect(state.current.busy).toBe(false));
      vi.useFakeTimers();
      let execution!: Promise<void>;
      await act(async () => {
        execution = state.current.send(request);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(800);
        await execution;
      });
      await act(async () => state.current.cancel());
      expect(state.current.canCancel).toBe(true);
      expect(state.current.notice).toContain('未确认服务端停止');
      expect(state.current.notice).toContain('任务与本轮不匹配');
      await act(async () => state.current.cancel());
      expect(state.current.canCancel).toBe(false);
      expect(state.current.notice).toContain('已停止接收');
      expect(calls('POST', '/api/v1/translations/job-1/cancel')).toHaveLength(2);
      expect(calls('POST', '/api/v1/translations')).toHaveLength(1);
    },
  );
});

describe('译境会话行为', () => {
  it('恢复 Cookie 设备后创建新会话，不读取或写入浏览器存储', async () => {
    const api = fixture();
    const get = vi.spyOn(Storage.prototype, 'getItem');
    const set = vi.spyOn(Storage.prototype, 'setItem');
    await ready(api);
    expect(api.createSession).toHaveBeenCalledWith(auth.csrf_token, expect.any(AbortSignal));
    expect(screen.queryByLabelText('一轮翻译')).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
  });

  it('支持 12 位配对码，配对后进入文字界面', async () => {
    const api = fixture();
    vi.mocked(api.auth).mockRejectedValue(
      new ApiError({ code: 'AUTH_REQUIRED', message: '请配对', retryable: false }, 401),
    );
    render(<App api={api} />);
    await waitFor(() => expect(screen.getByLabelText('12 位配对码')).not.toBeDisabled());
    fireEvent.change(screen.getByLabelText('12 位配对码'), { target: { value: 'ABCD EFGH IJKL' } });
    fireEvent.click(screen.getByRole('button', { name: /连接，开始翻译/ }));
    await waitFor(() => expect(screen.getByLabelText('原文')).toBeInTheDocument());
    expect(api.pair).toHaveBeenCalledWith('ABCDEFGHIJKL', expect.any(AbortSignal));
    expect(screen.queryByLabelText('12 位配对码')).not.toBeInTheDocument();
  });

  it('即时按 Unicode 码点计数，并阻止超过 4000 字符的请求', async () => {
    const api = fixture();
    await ready(api);
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '🙂你好' } });
    expect(screen.getByText('3 / 4000 字符')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '🙂'.repeat(4001) } });
    expect(screen.getByText('4001 / 4000 字符')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /开始翻译/ })).toBeDisabled();
    expect(api.translate).not.toHaveBeenCalled();
    expect(characterCount('a\n中🙂')).toBe(4);
  });

  it('译文中的 HTML 作为文本显示，不创建可执行节点', async () => {
    const api = fixture();
    const payload = '<img src=x onerror=alert(1)> <script>bad()</script>';
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, payload));
    await ready(api);
    enter();
    expect(await screen.findByText(payload)).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });

  it('预期错误只形成行内消息与可重试回合', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => ({
      ...submittedJob(api, '', 'failed'),
      error: {
        code: 'FORMAT_VALIDATION_FAILED',
        message: '格式需要重试',
        retryable: true,
        request_id: 'request-1',
      },
    }));
    await ready(api);
    enter();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('格式需要重试'));
    expect(screen.getByRole('button', { name: /重试此轮/ })).toBeEnabled();
    expect(screen.getByLabelText('原文')).toBeEnabled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('翻译中清空后，忽略即使不服从 AbortSignal 的迟到响应', async () => {
    const api = fixture();
    const old = deferred<Job>();
    vi.mocked(api.translate).mockReturnValue(old.promise);
    await ready(api);
    enter('old source');
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    expect(screen.queryByText('old source')).not.toBeInTheDocument();
    expect(screen.getByText('0 / 4000 字符')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('等待翻译'));
    await act(async () => old.resolve(job('迟到旧译文')));
    expect(screen.queryByText('迟到旧译文')).not.toBeInTheDocument();
    expect(api.deleteSession).toHaveBeenCalledWith(
      'session-1',
      auth.csrf_token,
      expect.any(AbortSignal),
    );
    expect(api.createSession).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('status')).toHaveTextContent('等待翻译');
  });

  it('旧请求 finally 不会解除新请求的忙碌状态', async () => {
    const api = fixture();
    const old = deferred<Job>();
    const latest = deferred<Job>();
    vi.mocked(api.translate).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
    await ready(api);
    enter('old');
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('等待翻译'));
    enter('new');
    await act(async () => old.resolve(job('旧内容')));
    expect(screen.getByRole('button', { name: /停止此轮/ })).toBeInTheDocument();
    expect(screen.queryByText('旧内容')).not.toBeInTheDocument();
    await act(async () => latest.resolve(submittedJob(api, '新的结果')));
    expect(screen.getByText('新的结果')).toBeInTheDocument();
  });

  it('手动删空进行中输入执行复位，但删空普通草稿保留已完成回合', async () => {
    const api = fixture();
    await ready(api);
    enter();
    await screen.findByText('你好');
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: 'draft' } });
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '' } });
    expect(screen.getByText('你好')).toBeInTheDocument();
    const pending = deferred<Job>();
    vi.mocked(api.translate).mockReturnValue(pending.promise);
    enter('next');
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: 'during' } });
    fireEvent.change(screen.getByLabelText('原文'), { target: { value: '' } });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('等待翻译'));
    await act(async () => pending.resolve(job('不能恢复')));
    expect(screen.queryByText('不能恢复')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('一轮翻译')).not.toBeInTheDocument();
  });

  it('重复提交和 Ctrl+Enter 共用同一入口并只提交一次', async () => {
    const api = fixture();
    const pending = deferred<Job>();
    vi.mocked(api.translate).mockReturnValue(pending.promise);
    await ready(api);
    const input = screen.getByLabelText('原文');
    fireEvent.change(input, { target: { value: 'Hello' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    fireEvent.submit(input.closest('form')!);
    expect(api.translate).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(submittedJob(api)));
  });

  it('取消轮询时向服务器发送 cancel，并忽略后续结果', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, '', 'running'));
    await ready(api);
    enter();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('正在翻译'));
    fireEvent.click(screen.getByRole('button', { name: /停止此轮/ }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已停止接收'));
    expect(api.cancel).toHaveBeenCalledWith('job-1', auth.csrf_token, expect.any(AbortSignal));
    expect(api.job).not.toHaveBeenCalled();
    expect(screen.queryByText('你好')).not.toBeInTheDocument();
  });

  it('退出失败仍显示撤销未确认，并保留重试退出入口', async () => {
    const api = fixture();
    vi.mocked(api.logout).mockRejectedValue(
      new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '无法连接电脑', retryable: true }),
    );
    await ready(api);
    fireEvent.click(screen.getByRole('button', { name: '退出' }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('尚未确认设备凭据撤销'),
    );
    expect(screen.getByRole('button', { name: '退出' })).toBeEnabled();
    expect(screen.getByRole('status')).not.toHaveTextContent('已退出设备连接');
  });

  it('清空失败仍保持界面清空，并明确服务器停止未确认', async () => {
    const api = fixture();
    await ready(api);
    enter();
    await screen.findByText('你好');
    vi.mocked(api.deleteSession).mockRejectedValue(
      new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }),
    );
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('未确认服务端停止'));
    expect(screen.queryByText('你好')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /开始翻译/ })).toBeDisabled();
  });

  it('断线后不会因 online 事件自动重放翻译', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockRejectedValue(
      new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }),
    );
    await ready(api);
    enter();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('连接断开'));
    fireEvent(window, new Event('offline'));
    fireEvent(window, new Event('online'));
    expect(api.translate).toHaveBeenCalledTimes(1);
  });

  it('内存中最多保留最近 20 轮，不使用持久存储', async () => {
    const api = fixture();
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    for (let index = 0; index < 23; index += 1) {
      await act(async () => state.current.send({ ...request, text: `Hello ${index}` }));
    }
    expect(state.current.turns).toHaveLength(20);
    expect(state.current.turns[0].request.text).toBe('Hello 3');
    expect(state.current.turns[19].request.text).toBe('Hello 22');
  });

  it('清空后迟到的复制反馈不会恢复旧状态', async () => {
    const clipboard = deferred<void>();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockReturnValue(clipboard.promise) },
    });
    const api = fixture();
    await ready(api);
    enter();
    await screen.findByText('你好');
    fireEvent.click(screen.getByRole('button', { name: /复制译文/ }));
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('等待翻译'));
    await act(async () => clipboard.resolve());
    expect(screen.getByRole('status')).toHaveTextContent('等待翻译');
  });

  it('清空失败保留待清理会话，重连先确认删除再创建新会话', async () => {
    const api = fixture();
    await ready(api);
    vi.mocked(api.deleteSession).mockRejectedValueOnce(
      new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }),
    );
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('未确认服务端停止'));
    expect(api.createSession).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已连接'));
    expect(api.deleteSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.deleteSession).mock.calls.map(([id]) => id)).toEqual([
      'session-1',
      'session-1',
    ]);
    expect(api.createSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.deleteSession).mock.invocationCallOrder[1]).toBeLessThan(
      vi.mocked(api.createSession).mock.invocationCallOrder[1],
    );
  });

  it('旧会话已不存在时按 404 成功清理并重新连接', async () => {
    const api = fixture();
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.mocked(api.deleteSession).mockRejectedValueOnce(
      new ApiError({ code: 'NOT_FOUND', message: '会话已过期', retryable: false }, 404),
    );
    await act(async () => state.current.connect());
    expect(state.current.session?.session_id).toBe('session-2');
    expect(state.current.connection).toBe('paired');
  });

  it('提交遇到过期会话保留原文并要求重连，不自动再次翻译', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockRejectedValueOnce(
      new ApiError({ code: 'NOT_FOUND', message: '会话已过期', retryable: false }, 404),
    );
    await ready(api);
    enter('保留这段原文');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('请重新连接后手动重试'),
    );
    expect(screen.getByText('保留这段原文')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重试此轮/ })).toBeDisabled();
    expect(api.translate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已连接'));
    expect(api.createSession).toHaveBeenCalledTimes(2);
    expect(api.translate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /重试此轮/ }));
    await screen.findByText('你好');
    expect(api.translate).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.translate).mock.calls[1][0]).toBe('session-2');
    expect(vi.mocked(api.translate).mock.calls[1][2].text).toBe('保留这段原文');
  });

  it('查询结果 404 不当作提交会话过期，也不自动重投文本', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, '', 'running'));
    vi.mocked(api.job).mockRejectedValue(
      new ApiError({ code: 'NOT_FOUND', message: '查询结果已过期', retryable: false }, 404),
    );
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => {
      execution = state.current.send(request);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
      await execution;
    });
    expect(state.current.notice).toContain('查询结果已过期');
    expect(state.current.session?.session_id).toBe('session-1');
    expect(api.translate).toHaveBeenCalledTimes(1);
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(state.current.turns[0].request.text).toBe('Hello');
  });

  it('超过 240 秒停止轮询后保留可取消入口', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, '', 'running'));
    vi.mocked(api.job).mockImplementation(async () => submittedJob(api, '', 'running'));
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    const time = vi.spyOn(Date, 'now').mockReturnValue(0);
    let execution!: Promise<void>;
    await act(async () => {
      execution = state.current.send(request);
    });
    time.mockReturnValue(240_001);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
      await execution;
    });
    expect(state.current.busy).toBe(false);
    expect(state.current.canCancel).toBe(true);
    expect(state.current.notice).toContain('4 分钟');
    await act(async () => state.current.cancel());
    expect(api.cancel).toHaveBeenCalledTimes(1);
    expect(state.current.canCancel).toBe(false);
  });

  it('取消未确认时仍可再次请求取消原任务', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, '', 'running'));
    vi.mocked(api.cancel).mockRejectedValueOnce(
      new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }),
    );
    await ready(api);
    enter();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('正在翻译'));
    fireEvent.click(screen.getByRole('button', { name: /停止此轮/ }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('未确认服务端停止'));
    fireEvent.click(screen.getByRole('button', { name: /停止此轮/ }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已停止接收'));
    expect(api.cancel).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.cancel).mock.calls.map(([id]) => id)).toEqual(['job-1', 'job-1']);
  });

  it('轮询收到 429 按 Retry-After 退避而不重新提交', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockImplementation(async () => submittedJob(api, '', 'running'));
    vi.mocked(api.job)
      .mockRejectedValueOnce(
        new ApiError({ code: 'RATE_LIMITED', message: '稍后查询', retryable: true }, 429, 3),
      )
      .mockImplementationOnce(async () => submittedJob(api));
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => {
      execution = state.current.send(request);
    });
    await act(async () => vi.advanceTimersByTimeAsync(800));
    expect(api.job).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(2900));
    expect(api.job).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
      await execution;
    });
    expect(api.job).toHaveBeenCalledTimes(2);
    expect(api.translate).toHaveBeenCalledTimes(1);
    expect(state.current.turns[0].status).toBe('done');
  });

  it('页面离开只尽力清理会话，不把设备退出；BFCache 返回创建新会话', async () => {
    const api = fixture();
    vi.spyOn(api, 'leaveSession').mockImplementation(() => undefined);
    await ready(api);
    fireEvent(window, new PageTransitionEvent('pagehide', { persisted: true }));
    expect(api.leaveSession).toHaveBeenCalledWith('session-1', auth.csrf_token);
    expect(api.logout).not.toHaveBeenCalled();
    fireEvent(window, new PageTransitionEvent('pageshow', { persisted: true }));
    await waitFor(() => expect(api.createSession).toHaveBeenCalledTimes(2));
    expect(api.deleteSession).toHaveBeenCalledWith(
      'session-1',
      auth.csrf_token,
      expect.any(AbortSignal),
    );
    expect(screen.queryByLabelText('一轮翻译')).not.toBeInTheDocument();
  });
});
