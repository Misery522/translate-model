import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { ApiError, TranslationApi } from './api';
import type { AgentResult, Job, TranslationRequest } from './types';
import { characterCount, useTranslator } from './useTranslator';

const auth = { device_id: 'device-1', device_name: '测试设备', auth_mode: 'cookie' as const, expires_at: '2099-01-01', csrf_token: 'csrf-memory-only' };
const request: TranslationRequest = { text: 'Hello', target_language: 'zh-Hans', source_language: 'auto', style: 'standard', domain: 'general', task_mode: 'auto' };
const result: AgentResult = { route: 'translate_text', detected_language: 'en', detection_status: 'detected', preserved_source: 'Hello', translated_text: '你好', annotated_copy: null, annotations: [], applied_terms: [], warnings: [], elapsed_ms: 1200 };
function job(text = '你好', status: Job['status'] = 'succeeded'): Job {
  return { job_id: 'job-1', session_id: 'session-1', client_request_id: 'request-1', generation: 1, status, created_at: '2026-09-07', expires_at: '2099-01-01', result: status === 'succeeded' ? { ...result, translated_text: text } : null, error: null };
}
function fixture() {
  const api = new TranslationApi();
  vi.spyOn(api, 'auth').mockResolvedValue(auth);
  vi.spyOn(api, 'pair').mockResolvedValue(auth);
  let sequence = 0;
  vi.spyOn(api, 'createSession').mockImplementation(async () => ({ session_id: `session-${++sequence}`, generation: 0, expires_at: '2099-01-01' }));
  vi.spyOn(api, 'deleteSession').mockResolvedValue();
  vi.spyOn(api, 'logout').mockResolvedValue();
  vi.spyOn(api, 'translate').mockResolvedValue(job());
  vi.spyOn(api, 'job').mockResolvedValue(job());
  vi.spyOn(api, 'cancel').mockResolvedValue(job('', 'cancelled'));
  return api;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
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
    vi.mocked(api.auth).mockRejectedValue(new ApiError({ code: 'AUTH_REQUIRED', message: '请配对', retryable: false }, 401));
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
    vi.mocked(api.translate).mockResolvedValue(job(payload));
    await ready(api);
    enter();
    expect(await screen.findByText(payload)).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });

  it('预期错误只形成行内消息与可重试回合', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockResolvedValue({ ...job('', 'failed'), error: { code: 'FORMAT_VALIDATION_FAILED', message: '格式需要重试', retryable: true, request_id: 'request-1' } });
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
    expect(api.deleteSession).toHaveBeenCalledWith('session-1', auth.csrf_token, expect.any(AbortSignal));
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
    await act(async () => latest.resolve(job('新的结果')));
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
    await act(async () => pending.resolve(job()));
  });

  it('取消轮询时向服务器发送 cancel，并忽略后续结果', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockResolvedValue(job('', 'running'));
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
    vi.mocked(api.logout).mockRejectedValue(new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '无法连接电脑', retryable: true }));
    await ready(api);
    fireEvent.click(screen.getByRole('button', { name: '退出' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('尚未确认设备凭据撤销'));
    expect(screen.getByRole('button', { name: '退出' })).toBeEnabled();
    expect(screen.getByRole('status')).not.toHaveTextContent('已退出设备连接');
  });

  it('清空失败仍保持界面清空，并明确服务器停止未确认', async () => {
    const api = fixture();
    await ready(api);
    enter();
    await screen.findByText('你好');
    vi.mocked(api.deleteSession).mockRejectedValue(new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }));
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('未确认服务端停止'));
    expect(screen.queryByText('你好')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /开始翻译/ })).toBeDisabled();
  });

  it('断线后不会因 online 事件自动重放翻译', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockRejectedValue(new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }));
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
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockReturnValue(clipboard.promise) } });
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
    vi.mocked(api.deleteSession).mockRejectedValueOnce(new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }));
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('未确认服务端停止'));
    expect(api.createSession).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('已连接'));
    expect(api.deleteSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.deleteSession).mock.calls.map(([id]) => id)).toEqual(['session-1', 'session-1']);
    expect(api.createSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.deleteSession).mock.invocationCallOrder[1]).toBeLessThan(vi.mocked(api.createSession).mock.invocationCallOrder[1]);
  });

  it('旧会话已不存在时按 404 成功清理并重新连接', async () => {
    const api = fixture();
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.mocked(api.deleteSession).mockRejectedValueOnce(new ApiError({ code: 'NOT_FOUND', message: '会话已过期', retryable: false }, 404));
    await act(async () => state.current.connect());
    expect(state.current.session?.session_id).toBe('session-2');
    expect(state.current.connection).toBe('paired');
  });

  it('提交遇到过期会话保留原文并要求重连，不自动再次翻译', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockRejectedValueOnce(new ApiError({ code: 'NOT_FOUND', message: '会话已过期', retryable: false }, 404));
    await ready(api);
    enter('保留这段原文');
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('请重新连接后手动重试'));
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
    vi.mocked(api.translate).mockResolvedValue(job('', 'running'));
    vi.mocked(api.job).mockRejectedValue(new ApiError({ code: 'NOT_FOUND', message: '查询结果已过期', retryable: false }, 404));
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => { execution = state.current.send(request); });
    await act(async () => { await vi.advanceTimersByTimeAsync(800); await execution; });
    expect(state.current.notice).toContain('查询结果已过期');
    expect(state.current.session?.session_id).toBe('session-1');
    expect(api.translate).toHaveBeenCalledTimes(1);
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(state.current.turns[0].request.text).toBe('Hello');
  });

  it('超过 240 秒停止轮询后保留可取消入口', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockResolvedValue(job('', 'running'));
    vi.mocked(api.job).mockResolvedValue(job('', 'running'));
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    const time = vi.spyOn(Date, 'now').mockReturnValue(0);
    let execution!: Promise<void>;
    await act(async () => { execution = state.current.send(request); });
    time.mockReturnValue(240_001);
    await act(async () => { await vi.advanceTimersByTimeAsync(800); await execution; });
    expect(state.current.busy).toBe(false);
    expect(state.current.canCancel).toBe(true);
    expect(state.current.notice).toContain('4 分钟');
    await act(async () => state.current.cancel());
    expect(api.cancel).toHaveBeenCalledTimes(1);
    expect(state.current.canCancel).toBe(false);
  });

  it('取消未确认时仍可再次请求取消原任务', async () => {
    const api = fixture();
    vi.mocked(api.translate).mockResolvedValue(job('', 'running'));
    vi.mocked(api.cancel).mockRejectedValueOnce(new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '连接断开', retryable: true }));
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
    vi.mocked(api.translate).mockResolvedValue(job('', 'running'));
    vi.mocked(api.job).mockRejectedValueOnce(new ApiError({ code: 'RATE_LIMITED', message: '稍后查询', retryable: true }, 429, 3)).mockResolvedValueOnce(job());
    const { result: state } = renderHook(() => useTranslator(api));
    await waitFor(() => expect(state.current.busy).toBe(false));
    vi.useFakeTimers();
    let execution!: Promise<void>;
    await act(async () => { execution = state.current.send(request); });
    await act(async () => vi.advanceTimersByTimeAsync(800));
    expect(api.job).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(2900));
    expect(api.job).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(900); await execution; });
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
    expect(api.deleteSession).toHaveBeenCalledWith('session-1', auth.csrf_token, expect.any(AbortSignal));
    expect(screen.queryByLabelText('一轮翻译')).not.toBeInTheDocument();
  });
});
