import { ApiError, jobResponse, workSessionResponse } from './api';
import type { DeviceAuth, TranslationRequest } from './types';
import type { TranslatorTransport } from './translatorTransport';

export type NativeInvoker = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export interface BackendStatus {
  origin: string | null;
  paired: boolean;
  generation: number;
  shortcut_available: boolean;
}

type ApiOperation =
  | {
      operation: 'health' | 'auth' | 'logout' | 'capabilities' | 'create_session' | 'glossary';
    }
  | { operation: 'pair'; code: string; device_name: string }
  | { operation: 'delete_session'; session_id: string }
  | {
      operation: 'translate';
      session_id: string;
      client_request_id: string;
      request: TranslationRequest;
    }
  | { operation: 'job' | 'cancel'; job_id: string };

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const invalidResponse = () =>
  new ApiError({
    code: 'INVALID_RESPONSE',
    message: '电脑返回的状态不完整，尚未确认任务结果，请停止或清空后再试。',
    retryable: true,
  });

// 不把异常原文透传给 React，避免桥接故障时暴露地址、原文或调试信息。
const messages: Readonly<Record<string, string>> = {
  INVALID_REQUEST: '请求参数不符合桌面安全约束。',
  FORBIDDEN: '当前窗口无权调用此操作。',
  INVALID_RESPONSE: '电脑返回的数据无法验证，任务状态尚未确认。',
  HOST_UNAVAILABLE: '桌面连接状态不可用，请重新启动译境。',
  STALE_OPERATION: '连接已重置，旧请求结果已丢弃。',
  PAIRING_REQUIRED: '请先使用电脑端的一次性配对码连接。',
  NETWORK_UNCONFIRMED: '连接未完成；请求可能已经送达，请先停止或清空此轮再重试。',
  REDIRECT_BLOCKED: '电脑服务发生跳转，请核对地址后重新配对。',
  ACCESS_DENIED: '电脑服务拒绝访问，请核对配对状态。',
  NOT_FOUND: '工作会话或任务不存在，可能已过期。',
  CONFLICT: '请求与电脑当前状态冲突，请重新连接。',
  REQUEST_TOO_LARGE: '请求超过电脑服务的大小限制。',
  RATE_LIMITED: '电脑服务繁忙，请稍后重试。',
  SERVICE_UNAVAILABLE: '电脑服务暂时不可用，请稍后重试。',
  REQUEST_REJECTED: '电脑服务拒绝了此请求，请检查输入。',
  INVALID_ORIGIN:
    '请输入 HTTPS 服务源地址，或带端口的本机 HTTP 地址；不能包含路径、凭据或查询参数。',
  BACKEND_NOT_CONFIGURED: '请先明确设置电脑服务地址。',
};

function bridgeError(value: unknown): ApiError {
  const known =
    record(value) && typeof value.code === 'string' && Object.hasOwn(messages, value.code);
  const code = known ? String(value.code) : 'NETWORK_UNCONFIRMED';
  const status =
    code !== 'NETWORK_UNCONFIRMED' &&
    known &&
    record(value) &&
    Number.isInteger(value.status) &&
    Number(value.status) >= 0 &&
    Number(value.status) <= 599
      ? Number(value.status)
      : 0;
  return new ApiError(
    {
      code,
      message: messages[code],
      retryable: code === 'NETWORK_UNCONFIRMED' || (record(value) && value.retryable === true),
    },
    status,
    code === 'RATE_LIMITED' ? 2 : 1,
  );
}

/** 仅用于提交配置前的友好检查。真正的地址白名单始终由 Rust 再次验证。 */
export function normalizeBackendOrigin(input: string): string {
  const raw = input.trim();
  const invalid = () =>
    new ApiError({
      code: 'INVALID_ORIGIN',
      message: messages.INVALID_ORIGIN,
      retryable: false,
    });
  if (!raw || raw.length > 1024 || /[\s\u0000-\u001f\u007f\\%@?#]/.test(raw)) throw invalid();
  const authority = raw.split('://')[1];
  if (!authority || (authority.includes('/') && authority.slice(authority.indexOf('/') + 1) !== ''))
    throw invalid();
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw invalid();
  }
  if (
    !url.hostname ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw invalid();
  if (url.protocol === 'http:') {
    const match = /^http:\/\/(127\.0\.0\.1|localhost):(\d+)\/?$/.exec(raw);
    if (!match || Number(match[2]) < 1024 || Number(match[2]) > 65535) throw invalid();
  } else if (url.protocol !== 'https:' || !raw.startsWith('https://')) throw invalid();
  return url.origin;
}

function backendStatusResponse(value: unknown): BackendStatus {
  if (
    !record(value) ||
    (value.origin !== null && typeof value.origin !== 'string') ||
    typeof value.paired !== 'boolean' ||
    typeof value.shortcut_available !== 'boolean' ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 0
  )
    throw invalidResponse();
  if (value.origin !== null) {
    try {
      normalizeBackendOrigin(String(value.origin));
    } catch {
      throw invalidResponse();
    }
  }
  return {
    origin: value.origin as string | null,
    paired: value.paired,
    generation: Number(value.generation),
    shortcut_available: value.shortcut_available,
  };
}

function nativeAuthResponse(value: unknown): DeviceAuth {
  if (
    !record(value) ||
    value.auth_mode !== 'bearer' ||
    value.csrf_token !== null ||
    'access_token' in value ||
    'token_type' in value ||
    !['device_id', 'device_name', 'expires_at'].every(
      (key) =>
        typeof value[key] === 'string' && Boolean(value[key]) && String(value[key]).length <= 256,
    ) ||
    !Number.isFinite(Date.parse(String(value.expires_at)))
  )
    throw invalidResponse();
  return {
    device_id: String(value.device_id),
    device_name: String(value.device_name),
    expires_at: String(value.expires_at),
    auth_mode: 'bearer',
    csrf_token: null,
  };
}

/**
 * 只将已命名的操作发送到 Rust；浏览器 fetch、Cookie 和 Bearer 令牌均不经过此类。
 * AbortSignal 只能停止等待桥接结果，不能终止已经送达 Rust/电脑的 HTTP 请求。
 */
export class NativeTranslationApi implements TranslatorTransport {
  constructor(private readonly invoke: NativeInvoker) {}

  private async call(
    command: string,
    args?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (signal?.aborted) throw new DOMException('已停止等待桌面响应', 'AbortError');
    return new Promise<unknown>((resolve, reject) => {
      let settled = false;
      const finish = (action: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        signal?.removeEventListener('abort', abort);
        action();
      };
      const abort = () =>
        finish(() => reject(new DOMException('已停止等待桌面响应', 'AbortError')));
      // Rust 的普通网络请求限时 15 秒；这里只为不可用的 IPC 提供等待上限。
      const timeout = setTimeout(() => finish(() => reject(bridgeError(null))), 20_000);
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) {
        abort();
        return;
      }
      Promise.resolve()
        .then(() => {
          if (signal?.aborted) throw new DOMException('已停止等待桌面响应', 'AbortError');
          return this.invoke(command, args);
        })
        .then(
          (value) => finish(() => resolve(value)),
          (error: unknown) => finish(() => reject(bridgeError(error))),
        );
    });
  }

  private async request(
    operation: ApiOperation,
    expectedStatus: number,
    signal?: AbortSignal,
  ): Promise<unknown> {
    const value = await this.call('api_request', { request: operation }, signal);
    if (!record(value) || value.status !== expectedStatus || !Object.hasOwn(value, 'body'))
      throw invalidResponse();
    if (expectedStatus === 204) {
      if (value.body !== null) throw invalidResponse();
      return undefined;
    }
    if (!record(value.body)) throw invalidResponse();
    return value.body;
  }

  async backendStatus(signal?: AbortSignal) {
    return backendStatusResponse(await this.call('backend_status', undefined, signal));
  }
  async configureBackend(origin: string, signal?: AbortSignal) {
    return backendStatusResponse(
      await this.call('configure_backend', { origin: normalizeBackendOrigin(origin) }, signal),
    );
  }
  async health(signal?: AbortSignal) {
    const value = await this.request({ operation: 'health' }, 200, signal);
    if (!record(value) || value.status !== 'ok' || value.api_version !== '1')
      throw invalidResponse();
    return { status: 'ok' as const, api_version: '1' as const };
  }
  async auth(signal?: AbortSignal) {
    return nativeAuthResponse(await this.request({ operation: 'auth' }, 200, signal));
  }
  async pair(code: string, signal?: AbortSignal) {
    return nativeAuthResponse(
      await this.request({ operation: 'pair', code, device_name: '译境文字宠物' }, 201, signal),
    );
  }
  async logout(_csrf: string | null, signal?: AbortSignal) {
    await this.request({ operation: 'logout' }, 204, signal);
  }
  async createSession(_csrf: string | null, signal?: AbortSignal) {
    return workSessionResponse(await this.request({ operation: 'create_session' }, 201, signal));
  }
  async deleteSession(id: string, _csrf: string | null, signal?: AbortSignal) {
    await this.request({ operation: 'delete_session', session_id: id }, 204, signal);
  }
  leaveSession(id: string, _csrf: string | null) {
    // 页面销毁时仅尽力清理，不宣称服务端已收到；宿主退出另有有限时间撤销。
    void this.deleteSession(id, null).catch(() => undefined);
  }
  async translate(
    session: string,
    clientRequestId: string,
    request: TranslationRequest,
    _csrf: string | null,
    signal?: AbortSignal,
  ) {
    return jobResponse(
      await this.request(
        {
          operation: 'translate',
          session_id: session,
          client_request_id: clientRequestId,
          request,
        },
        202,
        signal,
      ),
      { session_id: session, client_request_id: clientRequestId },
    );
  }
  async job(id: string, signal?: AbortSignal) {
    return jobResponse(await this.request({ operation: 'job', job_id: id }, 200, signal), {
      job_id: id,
    });
  }
  async cancel(id: string, _csrf: string | null, signal?: AbortSignal) {
    return jobResponse(await this.request({ operation: 'cancel', job_id: id }, 200, signal), {
      job_id: id,
    });
  }
  capabilities(signal?: AbortSignal) {
    return this.request({ operation: 'capabilities' }, 200, signal);
  }
  glossary(signal?: AbortSignal) {
    return this.request({ operation: 'glossary' }, 200, signal);
  }
}
