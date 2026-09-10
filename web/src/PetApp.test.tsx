import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import type { AgentResult, Job } from './types';
import PetApp from './PetApp';
import { NativeTranslationApi, type BackendStatus } from './nativeApi';

// 只隔离宿主入口；PetApp 与 useTranslator 都使用真实实现。
// 每个测试还会显式注入 api 和窗口，不能在普通 Vitest 中访问 Tauri。
vi.mock('./tauriRuntime', () => ({
  nativeApi: {},
  petWindowControls: {
    hide: vi.fn().mockResolvedValue(undefined),
    startDragging: vi.fn().mockResolvedValue(undefined),
  },
}));

const oldOrigin = 'http://127.0.0.1:8765';
const newOrigin = 'https://private.example';
const expiresAt = '2099-01-01T00:00:00+00:00';
const identity = {
  device_id: '68c1c4f4-a66a-4d5c-a1d8-253a7176f61e',
  device_name: '测试文字宠物',
  expires_at: expiresAt,
  auth_mode: 'bearer' as const,
  csrf_token: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function unconfirmed() {
  return new ApiError({
    code: 'NETWORK_UNCONFIRMED',
    message: '连接状态尚未确认。',
    retryable: true,
  });
}

function unpaired() {
  return new ApiError(
    {
      code: 'PAIRING_REQUIRED',
      message: '请使用一次性配对码连接。',
      retryable: false,
    },
    401,
  );
}

function submittedJob(
  api: NativeTranslationApi,
  status: Job['status'] = 'succeeded',
  result?: AgentResult,
): Job {
  const call = vi.mocked(api.translate).mock.calls.at(-1);
  if (!call) throw new Error('夹具须先收到真实 hook 提交，不能伪造 client_request_id。');
  const [session_id, client_request_id, request] = call;
  return {
    job_id: `504f7193-56f0-4517-ae82-${String(vi.mocked(api.translate).mock.calls.length).padStart(12, '0')}`,
    session_id,
    client_request_id,
    // 同一任务从提交到轮询/停止都保持这一代次，不随会话清空乱改。
    generation: 1,
    status,
    created_at: '2026-09-10T00:00:00+00:00',
    expires_at: expiresAt,
    result:
      status === 'succeeded'
        ? (result ?? {
            route: 'translate_text',
            detected_language: 'en',
            detection_status: 'detected',
            preserved_source: request.text,
            translated_text: `译文：${request.text}`,
            annotated_copy: null,
            annotations: [],
            applied_terms: [],
            warnings: [],
            elapsed_ms: 250,
          })
        : null,
    error: null,
  };
}

function fixture(configured = true) {
  const state: BackendStatus = {
    origin: configured ? oldOrigin : null,
    paired: configured,
    generation: 1,
    shortcut_available: false,
  };
  const invoke = vi.fn().mockRejectedValue(new Error('测试未声明的原生调用'));
  const api = new NativeTranslationApi(invoke);
  vi.spyOn(api, 'backendStatus').mockImplementation(async () => ({ ...state }));
  vi.spyOn(api, 'configureBackend').mockImplementation(async (origin) => {
    state.origin = origin;
    state.paired = false;
    state.generation += 1;
    return { ...state };
  });
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', api_version: '1' });
  vi.spyOn(api, 'auth').mockImplementation(async () => {
    if (!state.paired) throw unpaired();
    return { ...identity };
  });
  vi.spyOn(api, 'pair').mockImplementation(async () => {
    state.paired = true;
    return { ...identity };
  });
  let sessionSequence = 0;
  vi.spyOn(api, 'createSession').mockImplementation(async () => ({
    session_id: `00000000-0000-4000-8000-${String(++sessionSequence).padStart(12, '0')}`,
    generation: 0,
    expires_at: expiresAt,
  }));
  vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined);
  vi.spyOn(api, 'leaveSession').mockImplementation(() => undefined);
  vi.spyOn(api, 'logout').mockImplementation(async () => {
    state.paired = false;
  });
  vi.spyOn(api, 'translate').mockImplementation(async () => submittedJob(api));
  vi.spyOn(api, 'job').mockImplementation(async () => submittedJob(api));
  vi.spyOn(api, 'cancel').mockImplementation(async () => submittedJob(api, 'cancelled'));
  const windowControls = {
    hide: vi.fn().mockResolvedValue(undefined),
    startDragging: vi.fn().mockResolvedValue(undefined),
  };
  return { api, state, invoke, windowControls };
}

type Fixture = ReturnType<typeof fixture>;

function mount(context: Fixture) {
  return render(<PetApp api={context.api} windowControls={context.windowControls} />);
}

async function ready(context: Fixture) {
  const view = mount(context);
  await screen.findByRole('button', { name: '开始翻译' });
  const conversation = screen.getByRole('region', { name: '小译文字翻译' });
  expect(within(conversation).getByRole('status')).toHaveTextContent('已连接');
  return view;
}

async function chooseOrigin(origin = newOrigin) {
  fireEvent.click(screen.getByRole('button', { name: '服务地址' }));
  const input = await screen.findByLabelText('电脑服务源地址');
  fireEvent.change(input, { target: { value: origin } });
  fireEvent.click(screen.getByRole('button', { name: '退出旧连接并应用' }));
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText('想翻译什么？'), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole('button', { name: '开始翻译' }));
}

beforeEach(() => {
  Object.defineProperty(navigator, 'onLine', {
    configurable: true,
    value: true,
  });
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('宠物组件测试不得访问网络')));
});

describe('宠物小窗与真实共享翻译状态机', () => {
  it('首次打开只读取宿主状态，编辑地址不会自动配置或联网', async () => {
    const context = fixture(false);
    mount(context);
    const configure = await screen.findByRole('button', {
      name: '设置地址并连接',
    });
    await waitFor(() => expect(configure).toBeEnabled());
    fireEvent.change(screen.getByLabelText('电脑服务源地址'), {
      target: { value: newOrigin },
    });
    expect(context.api.backendStatus).toHaveBeenCalledTimes(1);
    expect(context.api.configureBackend).not.toHaveBeenCalled();
    expect(context.api.health).not.toHaveBeenCalled();
    expect(context.api.auth).not.toHaveBeenCalled();
    expect(context.api.pair).not.toHaveBeenCalled();
    expect(context.invoke).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('想翻译什么？')).not.toBeInTheDocument();
  });

  it('改地址必须等待旧连接退出后再配置，并清除旧窗口草稿', async () => {
    const context = fixture();
    const logout = deferred<void>();
    vi.mocked(context.api.logout).mockImplementationOnce(async () => {
      context.state.paired = false;
      await logout.promise;
    });
    await ready(context);
    fireEvent.change(screen.getByLabelText('想翻译什么？'), {
      target: { value: '旧电脑未发送的草稿' },
    });
    await chooseOrigin();
    await waitFor(() => expect(context.api.logout).toHaveBeenCalledTimes(1));
    expect(context.api.configureBackend).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('想翻译什么？')).not.toBeInTheDocument();
    await act(async () => {
      logout.resolve(undefined);
      await logout.promise;
    });
    await screen.findByLabelText('一次性配对码');
    expect(context.api.configureBackend).toHaveBeenCalledExactlyOnceWith(
      newOrigin,
      expect.any(AbortSignal),
    );
    expect(vi.mocked(context.api.logout).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(context.api.configureBackend).mock.invocationCallOrder[0],
    );
    expect(context.api.health).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('旧电脑未发送的草稿')).not.toBeInTheDocument();
    expect(context.api.translate).not.toHaveBeenCalled();
  });

  it('撤销失败不会自动换地址或恢复旧翻译区，必须第二次明确确认', async () => {
    const context = fixture();
    vi.mocked(context.api.logout).mockImplementationOnce(async () => {
      context.state.paired = false;
      throw unconfirmed();
    });
    await ready(context);
    await chooseOrigin();
    const confirm = await screen.findByRole('button', { name: '确认仍然切换' });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(screen.getByText(/未确认旧电脑的设备凭据已撤销/)).toBeInTheDocument();
    expect(context.api.configureBackend).not.toHaveBeenCalled();
    expect(context.api.auth).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('想翻译什么？')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('一次性配对码')).not.toBeInTheDocument();
    fireEvent.click(confirm);
    await screen.findByLabelText('一次性配对码');
    expect(context.api.configureBackend).toHaveBeenCalledExactlyOnceWith(
      newOrigin,
      expect.any(AbortSignal),
    );
    expect(context.api.logout).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/旧服务器撤销仍未确认/)).toBeInTheDocument();
  });

  it('撤销失败时也能选择重试退出，确认成功前仍不配置新地址', async () => {
    const context = fixture();
    vi.mocked(context.api.logout).mockRejectedValueOnce(unconfirmed());
    await ready(context);
    await chooseOrigin();
    const retry = await screen.findByRole('button', { name: '重试退出并切换' });
    await waitFor(() => expect(retry).toBeEnabled());
    expect(context.api.configureBackend).not.toHaveBeenCalled();
    fireEvent.click(retry);
    await screen.findByLabelText('一次性配对码');
    expect(context.api.logout).toHaveBeenCalledTimes(2);
    expect(context.api.configureBackend).toHaveBeenCalledTimes(1);
    expect(vi.mocked(context.api.logout).mock.invocationCallOrder[1]).toBeLessThan(
      vi.mocked(context.api.configureBackend).mock.invocationCallOrder[0],
    );
  });

  it('配置响应丢失时暂停翻译，不能挂着旧地址标签连接可能已切换的新服务', async () => {
    const context = fixture();
    vi.mocked(context.api.configureBackend).mockImplementationOnce(async (origin) => {
      // 模拟 Rust 已应用新源，但返回 JS 的确认响应丢失。
      context.state.origin = origin;
      context.state.paired = false;
      context.state.generation += 1;
      throw unconfirmed();
    });
    await ready(context);
    await chooseOrigin();
    await screen.findByText(/连接配置未确认，翻译已暂停/);
    expect(context.state.origin).toBe(newOrigin);
    expect(context.api.configureBackend).toHaveBeenCalledTimes(1);
    expect(context.api.auth).toHaveBeenCalledTimes(1);
    expect(context.api.health).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('想翻译什么？')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('一次性配对码')).not.toBeInTheDocument();
    expect(screen.getByLabelText('电脑服务源地址')).toHaveValue(newOrigin);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '设置地址并连接' })).toBeEnabled(),
    );
  });

  it('隐藏按钮不会触发标题拖动，也不撤销正在使用的配对', async () => {
    const context = fixture();
    await ready(context);
    const hide = screen.getByRole('button', {
      name: '隐藏到托盘，不停止当前任务',
    });
    fireEvent(hide, new MouseEvent('pointerdown', { bubbles: true, button: 0 }));
    fireEvent.click(hide);
    await waitFor(() => expect(context.windowControls.hide).toHaveBeenCalledTimes(1));
    expect(context.windowControls.startDragging).not.toHaveBeenCalled();
    expect(context.api.logout).not.toHaveBeenCalled();
    expect(context.api.cancel).not.toHaveBeenCalled();
    expect(screen.getByLabelText('想翻译什么？')).toBeInTheDocument();
    fireEvent(
      screen.getByTitle('拖动这里移动小译'),
      new MouseEvent('pointerdown', { bubbles: true, button: 0 }),
    );
    expect(context.windowControls.startDragging).toHaveBeenCalledTimes(1);
  });

  it('快捷键不可用和窗口隐藏失败都有文字提示，不冒称成功', async () => {
    const context = fixture();
    context.windowControls.hide.mockRejectedValueOnce(new Error('window failed'));
    await ready(context);
    expect(screen.getByText('快捷键不可用，请从托盘唤回')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '隐藏到托盘，不停止当前任务' }));
    await screen.findByText('暂时无法隐藏窗口；可继续在此翻译。');
    expect(screen.queryByText('window failed')).not.toBeInTheDocument();
    expect(screen.getByLabelText('想翻译什么？')).toBeInTheDocument();
  });

  it('代码、注释与风险中的 HTML 都按纯文本呈现，不生成脚本或图片元素', async () => {
    const context = fixture();
    const source = 'def greet():\n    return "<img src=x onerror=alert(1)>"';
    const annotation = '<script>window.__pet_xss = true</script>';
    const risk = '<iframe src="https://untrusted.example"></iframe>';
    const result: AgentResult = {
      route: 'annotate_code',
      detected_language: 'en',
      detection_status: 'detected',
      preserved_source: source,
      translated_text: null,
      annotated_copy: `# 目标语言注释：保留返回字符串\n${source}`,
      annotations: [
        {
          kind: '说明',
          source_fragment: source,
          explanation: annotation,
          location: '第 1 行',
          risk,
        },
      ],
      applied_terms: [],
      warnings: [risk],
      elapsed_ms: 250,
    };
    vi.mocked(context.api.translate).mockImplementation(async () =>
      submittedJob(context.api, 'succeeded', result),
    );
    const view = await ready(context);
    send(source);
    await screen.findByText('已保留原文，目标语言说明见下方。');
    fireEvent.click(screen.getByText('注释副本与说明'));
    expect(screen.getByText(annotation)).toBeInTheDocument();
    expect(view.container.textContent).toContain(source);
    expect(view.container.textContent).toContain(risk);
    expect(view.container.querySelector('script, img, iframe, [onerror]')).toBeNull();
    expect(view.container.innerHTML).toContain('&lt;script&gt;');
    expect(view.container.innerHTML).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(screen.getByRole('button', { name: '复制结果' })).toBeEnabled();
  });

  it('字符计数即时使用 Unicode 字符数，不必请求模型', async () => {
    const context = fixture();
    await ready(context);
    fireEvent.change(screen.getByLabelText('想翻译什么？'), {
      target: { value: '你好🙂' },
    });
    expect(screen.getByText('3 / 4000 字符')).toBeInTheDocument();
    expect(context.api.translate).not.toHaveBeenCalled();
  });

  it('翻译中清空立即复位并删除旧会话，迟到的成功结果不得覆盖新的翻译', async () => {
    const context = fixture();
    const delayed = deferred<Job>();
    // 此边界故意忽略 AbortSignal，模拟已经送达后台的原生请求继续完成。
    vi.mocked(context.api.translate).mockImplementationOnce(() => delayed.promise);
    await ready(context);
    send('旧会话中的私密原文');
    await waitFor(() => expect(context.api.translate).toHaveBeenCalledTimes(1));
    const firstCall = vi.mocked(context.api.translate).mock.calls[0];
    const oldResult = submittedJob(context.api);
    expect(screen.getByText('旧会话中的私密原文')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    expect(screen.getByLabelText('想翻译什么？')).toHaveValue('');
    expect(screen.getByText('0 / 4000 字符')).toBeInTheDocument();
    expect(screen.queryByLabelText('一轮独立翻译')).not.toBeInTheDocument();
    await screen.findByText('等待翻译');
    expect(context.api.deleteSession).toHaveBeenCalledWith(
      firstCall[0],
      null,
      expect.any(AbortSignal),
    );
    expect(firstCall[4]?.aborted).toBe(true);
    expect(context.api.createSession).toHaveBeenCalledTimes(2);

    send('新会话的原文');
    await screen.findByText('译文：新会话的原文');
    const secondCall = vi.mocked(context.api.translate).mock.calls[1];
    expect(secondCall[0]).not.toBe(firstCall[0]);
    expect(secondCall[1]).not.toBe(firstCall[1]);
    await act(async () => {
      delayed.resolve(oldResult);
      await delayed.promise;
    });
    expect(screen.queryByText('旧会话中的私密原文')).not.toBeInTheDocument();
    expect(screen.queryByText('译文：旧会话中的私密原文')).not.toBeInTheDocument();
    expect(screen.getByText('译文：新会话的原文')).toBeInTheDocument();
    expect(screen.getAllByLabelText('一轮独立翻译')).toHaveLength(1);
    expect(screen.getByText('0 / 4000 字符')).toBeInTheDocument();
    expect(context.api.translate).toHaveBeenCalledTimes(2);
  });
});
