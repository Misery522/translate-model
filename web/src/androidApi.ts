import { ApiError, jobResponse, workSessionResponse } from './api';
import type { JobBinding } from './api';
import {
  assertPublicResponse,
  isRecord,
  normalizeAndroidOrigin,
  validateAndroidOperation,
} from './androidProtocol';
import type {
  AndroidApiOperation,
  AndroidBackendStatus,
  AndroidBridgeCommand,
  AndroidInvoker,
} from './androidProtocol';
import type { DeviceAuth, Job, TranslationRequest } from './types';
import type { TranslatorTransport } from './translatorTransport';

const invalidResponse = () =>
  new ApiError({
    code: 'INVALID_RESPONSE',
    message: '电脑返回的状态无法验证，请停止或清空此轮后再试。',
    retryable: true,
  });
const stale = () =>
  new ApiError({
    code: 'STALE_OPERATION',
    message: '连接已重置，旧请求结果已丢弃。',
    retryable: false,
  });
const messages: Readonly<Record<string, string>> = {
  INVALID_REQUEST: '请求参数不符合手机客户端安全约束。',
  FORBIDDEN: '当前页面无权调用原生操作。',
  INVALID_RESPONSE: '电脑返回的数据无法验证，请清空此轮后再试。',
  STALE_OPERATION: '连接已重置，旧请求结果已丢弃。',
  PAIRING_REQUIRED: '请先使用电脑的一次性配对码连接。',
  NETWORK_UNCONFIRMED: '连接未完成；请求可能已送达，尚未确认服务端停止。',
  REDIRECT_BLOCKED: '电脑服务发生跳转，请核对地址后重新配对。',
  TLS_REJECTED: '无法验证电脑服务的安全证书，请检查地址和设备时间。',
  ACCESS_DENIED: '电脑服务拒绝访问，请核对配对状态。',
  NOT_FOUND: '工作会话或任务不存在，可能已经过期。',
  CONFLICT: '请求与电脑状态冲突，请重新连接。',
  RATE_LIMITED: '电脑服务繁忙，请稍后重试。',
  SERVICE_UNAVAILABLE: '电脑服务暂时不可用，请稍后重试。',
  REQUEST_TOO_LARGE: '请求超过服务的大小限制。',
  REQUEST_REJECTED: '电脑服务拒绝此请求，请检查输入。',
  BACKEND_NOT_CONFIGURED: '请先明确设置私人电脑服务地址。',
};

function bridgeError(value: unknown): ApiError {
  const code =
    isRecord(value) && typeof value.code === 'string' && Object.hasOwn(messages, value.code)
      ? value.code
      : 'NETWORK_UNCONFIRMED';
  const status =
    code !== 'NETWORK_UNCONFIRMED' &&
    isRecord(value) &&
    Number.isInteger(value.status) &&
    Number(value.status) >= 400 &&
    Number(value.status) <= 599
      ? Number(value.status)
      : 0;
  return new ApiError(
    {
      code,
      message: messages[code],
      retryable: code === 'NETWORK_UNCONFIRMED' || (isRecord(value) && value.retryable === true),
    },
    status,
    code === 'RATE_LIMITED' ? 2 : 1,
  );
}

function backendStatusResponse(value: unknown): AndroidBackendStatus {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 3 ||
    !['origin', 'paired', 'generation'].every((key) => Object.hasOwn(value, key)) ||
    (value.origin !== null && typeof value.origin !== 'string') ||
    typeof value.paired !== 'boolean' ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 0 ||
    (value.origin === null && value.paired)
  )
    throw invalidResponse();
  if (value.origin !== null) {
    try {
      if (normalizeAndroidOrigin(String(value.origin)) !== value.origin) throw invalidResponse();
    } catch {
      throw invalidResponse();
    }
  }
  return {
    origin: value.origin as string | null,
    paired: value.paired,
    generation: Number(value.generation),
  };
}

function nativeAuthResponse(value: unknown): DeviceAuth {
  if (
    !isRecord(value) ||
    value.auth_mode !== 'bearer' ||
    value.csrf_token !== null ||
    Object.keys(value).length !== 5 ||
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

interface TrackedJob {
  binding: JobBinding;
  terminal: boolean;
}
interface PendingSubmission {
  sessionId: string;
}
const terminalStatuses = new Set<Job['status']>(['succeeded', 'failed', 'cancelled', 'timed_out']);

/** 纯协议基础：没有注册 Capacitor 插件，也不包含真实 Java 网络或令牌存储。 */
export class AndroidTranslationApi implements TranslatorTransport {
  private epoch = 0;
  private generation: number | null = null;
  private origin: string | null = null;
  private readonly jobs = new Map<string, TrackedJob>();
  private readonly pendingSubmissions = new Set<PendingSubmission>();

  constructor(private readonly invoke: AndroidInvoker) {}

  private clearTracking(): void {
    this.jobs.clear();
    this.pendingSubmissions.clear();
  }
  private reserveSubmission(sessionId: string): PendingSubmission {
    // 活动任务和仍在返回途中的提交不可回收；只淘汰最早确认的终态绑定。
    while (this.jobs.size + this.pendingSubmissions.size >= 128) {
      const oldest = Array.from(this.jobs).find(([, tracked]) => tracked.terminal);
      if (!oldest) throw bridgeError({ code: 'REQUEST_REJECTED' });
      this.jobs.delete(oldest[0]);
    }
    const submission = { sessionId };
    this.pendingSubmissions.add(submission);
    return submission;
  }
  private confirmJob(job: Job, tracked: TrackedJob): Job {
    // 条目身份必须仍在当前连接中，不能让迟到结果重建已删会话或已回收任务。
    if (
      this.jobs.get(job.job_id) !== tracked ||
      (tracked.terminal && !terminalStatuses.has(job.status))
    )
      throw stale();
    if (!tracked.terminal && terminalStatuses.has(job.status)) {
      tracked.terminal = true;
      this.jobs.delete(job.job_id);
      this.jobs.set(job.job_id, tracked);
    }
    return job;
  }

  private async call(
    command: AndroidBridgeCommand,
    epoch: number,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (action: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        action();
      };
      const abort = () => finish(() => reject(new DOMException('请求已取消', 'AbortError')));
      const timer = setTimeout(() => finish(() => reject(bridgeError(null))), 20_000);
      signal?.addEventListener('abort', abort, { once: true });
      Promise.resolve()
        .then(() => {
          if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
          if (this.epoch !== epoch) throw stale();
          return this.invoke(command);
        })
        .then(
          (value) =>
            finish(() => {
              if (signal?.aborted) reject(new DOMException('请求已取消', 'AbortError'));
              else if (this.epoch !== epoch) reject(stale());
              else resolve(value);
            }),
          (error: unknown) =>
            finish(() => {
              if (signal?.aborted) reject(new DOMException('请求已取消', 'AbortError'));
              else if (this.epoch !== epoch) reject(stale());
              else reject(bridgeError(error));
            }),
        );
    });
  }

  private requireGeneration(): number {
    if (this.generation === null || !this.origin)
      throw bridgeError({ code: 'BACKEND_NOT_CONFIGURED' });
    return this.generation;
  }
  private bearerCsrf(csrf: string | null): void {
    if (csrf !== null)
      throw new ApiError({
        code: 'AUTH_MODE_MISMATCH',
        message: '手机客户端必须使用原生 Bearer 配对，不能混入网页 CSRF。',
        retryable: false,
      });
  }
  private async request(
    input: AndroidApiOperation,
    status: number,
    signal?: AbortSignal,
    advance = false,
  ): Promise<unknown> {
    const request = validateAndroidOperation(input);
    const generation = this.requireGeneration();
    const epoch = this.epoch;
    const value = await this.call({ command: 'api_request', generation, request }, epoch, signal);
    if (this.epoch !== epoch) throw stale();
    if (
      !isRecord(value) ||
      Object.keys(value).length !== 3 ||
      value.status !== status ||
      !Object.hasOwn(value, 'body') ||
      !Number.isSafeInteger(value.generation) ||
      Number(value.generation) < 0
    )
      throw invalidResponse();
    if (advance ? Number(value.generation) <= generation : value.generation !== generation)
      throw stale();
    try {
      assertPublicResponse(value.body);
    } catch {
      throw invalidResponse();
    }
    if (status === 204 ? value.body !== null : !isRecord(value.body)) throw invalidResponse();
    if (advance) this.generation = Number(value.generation);
    return value.body;
  }

  async backendStatus(signal?: AbortSignal): Promise<AndroidBackendStatus> {
    const epoch = this.epoch;
    const status = backendStatusResponse(
      await this.call({ command: 'backend_status' }, epoch, signal),
    );
    if (this.epoch !== epoch) throw stale();
    if (status.generation !== this.generation || status.origin !== this.origin) {
      this.epoch += 1;
      this.clearTracking();
    }
    this.generation = status.generation;
    this.origin = status.origin;
    return status;
  }
  async configureBackend(input: string, signal?: AbortSignal): Promise<AndroidBackendStatus> {
    const origin = normalizeAndroidOrigin(input);
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    const previous = this.generation;
    const epoch = ++this.epoch;
    this.generation = null;
    this.origin = null;
    this.clearTracking();
    const status = backendStatusResponse(
      await this.call({ command: 'configure_backend', origin }, epoch, signal),
    );
    if (this.epoch !== epoch) throw stale();
    if (
      status.origin !== origin ||
      status.paired ||
      (previous !== null && status.generation <= previous)
    )
      throw invalidResponse();
    this.generation = status.generation;
    this.origin = origin;
    return status;
  }
  async health(signal?: AbortSignal) {
    const epoch = this.epoch;
    const value = await this.request({ operation: 'health' }, 200, signal);
    if (this.epoch !== epoch) throw stale();
    if (!isRecord(value) || value.status !== 'ok' || value.api_version !== '1')
      throw invalidResponse();
    return { status: 'ok' as const, api_version: '1' as const };
  }
  async auth(signal?: AbortSignal) {
    const epoch = this.epoch;
    const value = await this.request({ operation: 'auth' }, 200, signal);
    if (this.epoch !== epoch) throw stale();
    return nativeAuthResponse(value);
  }
  async pair(code: string, signal?: AbortSignal) {
    validateAndroidOperation({ operation: 'pair', code, device_name: '译境 Android' });
    // 仅在用户再次提交配对时读回宿主状态，不自动重发未确认的旧配对码。
    if (this.generation === null) await this.backendStatus(signal);
    this.requireGeneration();
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    const epoch = ++this.epoch;
    this.clearTracking();
    try {
      const value = await this.request(
        { operation: 'pair', code, device_name: '译境 Android' },
        201,
        signal,
        true,
      );
      if (this.epoch !== epoch) throw stale();
      return nativeAuthResponse(value);
    } catch (error) {
      // 旧配对不能在失败清理时破坏随后已经建立的新连接。
      if (this.epoch === epoch) this.generation = null;
      throw error;
    }
  }
  async logout(csrf: string | null, signal?: AbortSignal) {
    this.bearerCsrf(csrf);
    this.requireGeneration();
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    const epoch = ++this.epoch;
    this.clearTracking();
    try {
      await this.request({ operation: 'logout' }, 204, signal, true);
      if (this.epoch !== epoch) throw stale();
    } catch (error) {
      if (this.epoch === epoch) this.generation = null;
      throw error;
    }
  }
  async createSession(csrf: string | null, signal?: AbortSignal) {
    this.bearerCsrf(csrf);
    const epoch = this.epoch;
    const value = await this.request({ operation: 'create_session' }, 201, signal);
    if (this.epoch !== epoch) throw stale();
    const session = workSessionResponse(value);
    try {
      // 共享网页契约仍允许原有会话格式，Android 需与原生 UUID 白名单一致。
      validateAndroidOperation({ operation: 'delete_session', session_id: session.session_id });
    } catch {
      throw invalidResponse();
    }
    return session;
  }
  async deleteSession(id: string, csrf: string | null, signal?: AbortSignal) {
    this.bearerCsrf(csrf);
    const epoch = this.epoch;
    await this.request({ operation: 'delete_session', session_id: id }, 204, signal);
    if (this.epoch !== epoch) throw stale();
    for (const [jobId, tracked] of this.jobs)
      if (tracked.binding.session_id === id) this.jobs.delete(jobId);
    for (const submission of this.pendingSubmissions)
      if (submission.sessionId === id) this.pendingSubmissions.delete(submission);
  }
  leaveSession(id: string, csrf: string | null) {
    void this.deleteSession(id, csrf).catch(() => undefined);
  }
  async translate(
    session: string,
    clientRequestId: string,
    request: TranslationRequest,
    csrf: string | null,
    signal?: AbortSignal,
  ) {
    this.bearerCsrf(csrf);
    const input = validateAndroidOperation({
      operation: 'translate',
      session_id: session,
      client_request_id: clientRequestId,
      request,
    });
    this.requireGeneration();
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError');
    const epoch = this.epoch;
    const submission = this.reserveSubmission(session);
    try {
      const value = await this.request(input, 202, signal);
      if (this.epoch !== epoch || !this.pendingSubmissions.has(submission)) throw stale();
      const job = jobResponse(value, { session_id: session, client_request_id: clientRequestId });
      try {
        validateAndroidOperation({ operation: 'job', job_id: job.job_id });
      } catch {
        throw invalidResponse();
      }
      const existing = this.jobs.get(job.job_id);
      if (existing) return this.confirmJob(jobResponse(job, existing.binding), existing);
      const tracked = {
        binding: {
          job_id: job.job_id,
          session_id: job.session_id,
          client_request_id: job.client_request_id,
          generation: job.generation,
        },
        terminal: false,
      };
      this.jobs.set(job.job_id, tracked);
      return this.confirmJob(job, tracked);
    } finally {
      this.pendingSubmissions.delete(submission);
    }
  }
  private tracked(id: string): TrackedJob {
    const tracked = this.jobs.get(id);
    if (!tracked) throw bridgeError({ code: 'INVALID_REQUEST' });
    return tracked;
  }
  async job(id: string, signal?: AbortSignal): Promise<Job> {
    const epoch = this.epoch;
    const tracked = this.tracked(id);
    const value = await this.request({ operation: 'job', job_id: id }, 200, signal);
    if (this.epoch !== epoch) throw stale();
    return this.confirmJob(jobResponse(value, tracked.binding), tracked);
  }
  async cancel(id: string, csrf: string | null, signal?: AbortSignal): Promise<Job> {
    this.bearerCsrf(csrf);
    const epoch = this.epoch;
    const tracked = this.tracked(id);
    const value = await this.request({ operation: 'cancel', job_id: id }, 200, signal);
    if (this.epoch !== epoch) throw stale();
    return this.confirmJob(jobResponse(value, tracked.binding), tracked);
  }
}
