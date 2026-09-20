import type {
  ApiProblem,
  AuthView,
  DeviceAuth,
  Job,
  PairView,
  TranslationRequest,
  WorkSession,
} from './types';
import type { TranslatorTransport } from './translatorTransport';

export class ApiError extends Error {
  constructor(
    public problem: ApiProblem,
    public status = 0,
    public retryAfter = 1,
  ) {
    super(problem.message);
  }
}

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const optionalText = (value: unknown) =>
  value === undefined || value === null || typeof value === 'string';
const optionalArray = (value: unknown, valid: (item: unknown) => boolean) =>
  value === undefined || (Array.isArray(value) && value.every(valid));

// OpenAPI 提供编译期类型；运行时仍须验证响应，不能把畸形数据视为任务已结束。
function validResult(value: unknown): boolean {
  return (
    record(value) &&
    ['translate_text', 'annotate_code', 'annotate_special', 'mixed_document'].includes(
      String(value.route),
    ) &&
    typeof value.detected_language === 'string' &&
    ['detected', 'uncertain', 'mixed'].includes(String(value.detection_status)) &&
    typeof value.preserved_source === 'string' &&
    typeof value.elapsed_ms === 'number' &&
    Number.isFinite(value.elapsed_ms) &&
    value.elapsed_ms >= 0 &&
    optionalText(value.translated_text) &&
    optionalText(value.annotated_copy) &&
    optionalArray(value.warnings, (item) => typeof item === 'string') &&
    optionalArray(
      value.annotations,
      (item) =>
        record(item) &&
        typeof item.kind === 'string' &&
        typeof item.source_fragment === 'string' &&
        typeof item.explanation === 'string' &&
        optionalText(item.location) &&
        optionalText(item.risk),
    ) &&
    optionalArray(
      value.applied_terms,
      (item) =>
        record(item) &&
        typeof item.source === 'string' &&
        typeof item.target === 'string' &&
        Number.isInteger(item.count) &&
        Number(item.count) > 0,
    )
  );
}

export type JobBinding = Partial<
  Pick<Job, 'job_id' | 'session_id' | 'client_request_id' | 'generation'>
>;

export function jobResponse(value: unknown, expected: JobBinding = {}): Job {
  const valid =
    record(value) &&
    ['job_id', 'session_id', 'client_request_id', 'created_at', 'expires_at'].every(
      (key) => typeof value[key] === 'string' && Boolean(value[key]),
    ) &&
    Number.isInteger(value.generation) &&
    Number(value.generation) >= 0 &&
    ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out'].includes(
      String(value.status),
    ) &&
    (value.result === null || validResult(value.result)) &&
    (value.status !== 'succeeded' || validResult(value.result)) &&
    (value.error === null ||
      (record(value.error) &&
        typeof value.error.code === 'string' &&
        typeof value.error.message === 'string' &&
        typeof value.error.retryable === 'boolean' &&
        typeof value.error.request_id === 'string'));
  if (!valid)
    throw new ApiError({
      code: 'INVALID_RESPONSE',
      message: '电脑返回了不完整的任务状态，请停止或清空此轮后再试。',
      retryable: true,
    });
  const job = value as unknown as Job;
  if (
    Object.entries(expected).some(
      ([key, expectedValue]) => job[key as keyof JobBinding] !== expectedValue,
    )
  )
    throw new ApiError({
      code: 'INVALID_RESPONSE',
      message: '电脑返回的任务与本轮不匹配，请停止或清空此轮后再试。',
      retryable: true,
    });
  return job;
}

export function workSessionResponse(value: unknown): WorkSession {
  if (
    !record(value) ||
    typeof value.session_id !== 'string' ||
    !value.session_id ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 0 ||
    typeof value.expires_at !== 'string' ||
    !Number.isFinite(Date.parse(value.expires_at))
  ) {
    throw new ApiError({
      code: 'INVALID_RESPONSE',
      message: '工作会话无法验证，请重新连接。',
      retryable: true,
    });
  }
  return value as unknown as WorkSession;
}

export class TranslationApi implements TranslatorTransport {
  private async request<T>(
    path: string,
    method = 'GET',
    csrf?: string | null,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    // 接口兼容原生的 null CSRF，不表示网页可省略 Cookie 写入保护。
    if (method !== 'GET' && path !== '/pair/exchange' && !csrf) {
      throw new ApiError(
        { code: 'AUTH_MODE_MISMATCH', message: '网页配对状态无效，请重新连接。', retryable: false },
        403,
      );
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    const timeout = setTimeout(abort, 15_000);
    try {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        credentials: 'include',
        cache: 'no-store',
        redirect: 'error',
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      if (response.status === 204) return undefined as T;
      // 读取流失败与 JSON 语法错误不同：前者必须保留“可能已提交”的不确定性。
      const text = await response.text();
      let data: unknown;
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
      if (!response.ok) {
        const problem = record(data) && record(data.error) ? data.error : undefined;
        throw new ApiError(
          {
            code: typeof problem?.code === 'string' ? problem.code : 'HTTP_ERROR',
            message:
              typeof problem?.message === 'string'
                ? problem.message
                : '电脑服务暂时无法处理，请稍后重试。',
            retryable: Boolean(problem?.retryable),
            request_id: typeof problem?.request_id === 'string' ? problem.request_id : undefined,
          },
          response.status,
          Math.max(1, Math.min(60, Number(response.headers.get('Retry-After')) || 1)),
        );
      }
      if (!record(data))
        throw new ApiError(
          {
            code: 'INVALID_RESPONSE',
            message: '电脑返回了无法识别的数据，任务状态尚未确认。',
            retryable: true,
          },
          response.status,
        );
      return data as T;
    } catch (error) {
      if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
      if (error instanceof ApiError) throw error;
      throw new ApiError({
        code: 'NETWORK_UNCONFIRMED',
        message: '暂时无法连接电脑。请求状态尚未确认，恢复连接后可手动重试。',
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
    }
  }
  private cookieAuth(value: AuthView | PairView): DeviceAuth {
    if (
      value.auth_mode !== 'cookie' ||
      typeof value.csrf_token !== 'string' ||
      !value.csrf_token ||
      ('access_token' in value && value.access_token !== null)
    ) {
      throw new ApiError({
        code: 'AUTH_MODE_MISMATCH',
        message: '此网页需要受保护的 Cookie 配对，请检查电脑服务设置。',
        retryable: false,
      });
    }
    return {
      device_id: value.device_id,
      device_name: value.device_name,
      expires_at: value.expires_at,
      auth_mode: 'cookie',
      csrf_token: value.csrf_token,
    };
  }
  async auth(signal?: AbortSignal) {
    return this.cookieAuth(
      await this.request<AuthView>('/auth/session', 'GET', undefined, undefined, signal),
    );
  }
  async pair(code: string, signal?: AbortSignal) {
    return this.cookieAuth(
      await this.request<PairView>(
        '/pair/exchange',
        'POST',
        undefined,
        { code, device_name: '译境网页', auth_mode: 'cookie' },
        signal,
      ),
    );
  }
  logout(csrf: string | null, signal?: AbortSignal) {
    return this.request<void>('/auth/session', 'DELETE', csrf, undefined, signal);
  }
  async createSession(csrf: string | null, signal?: AbortSignal) {
    return workSessionResponse(await this.request<unknown>('/sessions', 'POST', csrf, {}, signal));
  }
  deleteSession(id: string, csrf: string | null, signal?: AbortSignal) {
    return this.request<void>(
      `/sessions/${encodeURIComponent(id)}`,
      'DELETE',
      csrf,
      undefined,
      signal,
    );
  }
  leaveSession(id: string, csrf: string | null) {
    if (!csrf) return;
    // 页面关闭时仅尽力清理，不将请求已发出解释为服务器已经完成取消。
    void fetch(`/api/v1/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'error',
      headers: { 'X-CSRF-Token': csrf },
      keepalive: true,
    }).catch(() => undefined);
  }
  async translate(
    session: string,
    clientRequestId: string,
    request: TranslationRequest,
    csrf: string | null,
    signal?: AbortSignal,
  ) {
    return jobResponse(
      await this.request<unknown>(
        '/translations',
        'POST',
        csrf,
        { session_id: session, client_request_id: clientRequestId, request },
        signal,
      ),
      { session_id: session, client_request_id: clientRequestId },
    );
  }
  async job(id: string, signal?: AbortSignal) {
    return jobResponse(
      await this.request<unknown>(
        `/translations/${encodeURIComponent(id)}`,
        'GET',
        undefined,
        undefined,
        signal,
      ),
      { job_id: id },
    );
  }
  async cancel(id: string, csrf: string | null, signal?: AbortSignal) {
    return jobResponse(
      await this.request<unknown>(
        `/translations/${encodeURIComponent(id)}/cancel`,
        'POST',
        csrf,
        {},
        signal,
      ),
      { job_id: id },
    );
  }
}

export function describeError(error: unknown): string {
  return error instanceof ApiError ? error.message : '操作未完成，请重试。';
}

export function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const done = () => {
      signal.removeEventListener('abort', abort);
      resolve();
    };
    const timer = setTimeout(done, ms);
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(new DOMException('请求已取消', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}
