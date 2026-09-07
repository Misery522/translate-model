import type { ApiProblem, AuthView, DeviceAuth, Job, PairView, TranslationRequest, WorkSession } from './types';

export class ApiError extends Error {
  constructor(public problem: ApiProblem, public status = 0, public retryAfter = 1) { super(problem.message); }
}

export class TranslationApi {
  private async request<T>(path: string, method = 'GET', csrf?: string, body?: unknown, signal?: AbortSignal): Promise<T> {
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
        method, headers, credentials: 'include', cache: 'no-store', redirect: 'error',
        body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      });
      if (response.status === 204) return undefined as T;
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const problem = data?.error;
        throw new ApiError({
          code: typeof problem?.code === 'string' ? problem.code : 'HTTP_ERROR',
          message: typeof problem?.message === 'string' ? problem.message : '电脑服务暂时无法处理，请稍后重试。',
          retryable: Boolean(problem?.retryable),
          request_id: typeof problem?.request_id === 'string' ? problem.request_id : undefined,
        }, response.status, Math.max(1, Math.min(60, Number(response.headers.get('Retry-After')) || 1)));
      }
      if (!data || typeof data !== 'object') throw new ApiError({ code: 'INVALID_RESPONSE', message: '电脑返回了无法识别的数据，请刷新后重试。', retryable: false });
      return data as T;
    } catch (error) {
      if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
      if (error instanceof ApiError) throw error;
      throw new ApiError({ code: 'NETWORK_UNCONFIRMED', message: '暂时无法连接电脑。请求状态尚未确认，恢复连接后可手动重试。', retryable: true });
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
    }
  }
  private cookieAuth(value: AuthView | PairView): DeviceAuth {
    if (value.auth_mode !== 'cookie' || typeof value.csrf_token !== 'string' || !value.csrf_token ||
      ('access_token' in value && value.access_token !== null)) {
      throw new ApiError({ code: 'AUTH_MODE_MISMATCH', message: '此网页需要受保护的 Cookie 配对，请检查电脑服务设置。', retryable: false });
    }
    return { device_id: value.device_id, device_name: value.device_name, expires_at: value.expires_at, auth_mode: 'cookie', csrf_token: value.csrf_token };
  }
  async auth(signal?: AbortSignal) {
    return this.cookieAuth(await this.request<AuthView>('/auth/session', 'GET', undefined, undefined, signal));
  }
  async pair(code: string, signal?: AbortSignal) {
    return this.cookieAuth(await this.request<PairView>('/pair/exchange', 'POST', undefined, { code, device_name: '译境网页', auth_mode: 'cookie' }, signal));
  }
  logout(csrf: string, signal?: AbortSignal) { return this.request<void>('/auth/session', 'DELETE', csrf, undefined, signal); }
  createSession(csrf: string, signal?: AbortSignal) { return this.request<WorkSession>('/sessions', 'POST', csrf, {}, signal); }
  deleteSession(id: string, csrf: string, signal?: AbortSignal) { return this.request<void>(`/sessions/${encodeURIComponent(id)}`, 'DELETE', csrf, undefined, signal); }
  leaveSession(id: string, csrf: string) {
    // 页面关闭时仅尽力清理，不将请求已发出解释为服务器已经完成取消。
    void fetch(`/api/v1/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE', credentials: 'include', cache: 'no-store', redirect: 'error',
      headers: { 'X-CSRF-Token': csrf }, keepalive: true,
    }).catch(() => undefined);
  }
  translate(session: string, clientRequestId: string, request: TranslationRequest, csrf: string, signal?: AbortSignal) {
    return this.request<Job>('/translations', 'POST', csrf, { session_id: session, client_request_id: clientRequestId, request }, signal);
  }
  job(id: string, signal?: AbortSignal) { return this.request<Job>(`/translations/${encodeURIComponent(id)}`, 'GET', undefined, undefined, signal); }
  cancel(id: string, csrf: string, signal?: AbortSignal) { return this.request<Job>(`/translations/${encodeURIComponent(id)}/cancel`, 'POST', csrf, {}, signal); }
}

export function describeError(error: unknown): string {
  return error instanceof ApiError ? error.message : '操作未完成，请重试。';
}

export function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const done = () => { signal.removeEventListener('abort', abort); resolve(); };
    const timer = setTimeout(done, ms);
    const abort = () => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(new DOMException('请求已取消', 'AbortError')); };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}
