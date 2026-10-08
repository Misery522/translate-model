import { ApiError } from './api';
import type { TranslationRequest } from './types';

export type AndroidApiOperation =
  | { operation: 'health' | 'auth' | 'logout' | 'create_session' }
  | { operation: 'pair'; code: string; device_name: string }
  | { operation: 'delete_session'; session_id: string }
  | {
      operation: 'translate';
      session_id: string;
      client_request_id: string;
      request: TranslationRequest;
    }
  | { operation: 'job' | 'cancel'; job_id: string };

/** 原生实现必须重复验证白名单；此接口不是任意 HTTP 或工具调用代理。 */
export type AndroidBridgeCommand =
  | { command: 'backend_status' }
  | { command: 'configure_backend'; origin: string }
  | { command: 'api_request'; generation: number; request: AndroidApiOperation };
export type AndroidInvoker = (command: AndroidBridgeCommand) => Promise<unknown>;
export interface AndroidBackendStatus {
  origin: string | null;
  paired: boolean;
  generation: number;
}

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const ownKeys = (value: Record<string, unknown>, fields: string[]) =>
  Object.keys(value).length === fields.length &&
  fields.every((field) => Object.hasOwn(value, field));
const uuid = (value: unknown): value is string =>
  typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const invalidRequest = () =>
  new ApiError({
    code: 'INVALID_REQUEST',
    message: '请求参数不符合手机客户端安全约束。',
    retryable: false,
  });

/** 首版仅支持私人 Serve，绑定一个明确源；域名后缀本身不证明身份可信。 */
export function normalizeAndroidOrigin(input: string): string {
  const invalid = () =>
    new ApiError({
      code: 'INVALID_ORIGIN',
      message: '请输入私人 Serve 的 HTTPS 源地址，不含路径、凭据、查询或非标准端口。',
      retryable: false,
    });
  if (
    typeof input !== 'string' ||
    input.length > 1024 ||
    !/^https:\/\/[^/]+\/?$/.test(input) ||
    /[\s\u0000-\u001f\u007f\\%@?#]/.test(input)
  )
    throw invalid();
  let url: URL;
  try {
    url = new URL(input);
  } catch {
    throw invalid();
  }
  const label = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?';
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.port ||
    url.pathname !== '/' ||
    url.search ||
    url.hash ||
    !new RegExp(`^${label}\\.${label}\\.ts\\.net$`, 'i').test(url.hostname)
  )
    throw invalid();
  return url.origin;
}

/** 验证后创建纯数据副本，避免调用期间外部对象改写请求。 */
export function validateAndroidOperation(value: unknown): AndroidApiOperation {
  if (!isRecord(value)) throw invalidRequest();
  const operation = value.operation;
  const simple = ['health', 'auth', 'logout', 'create_session'];
  if (typeof operation === 'string' && simple.includes(operation)) {
    if (!ownKeys(value, ['operation'])) throw invalidRequest();
  } else if (operation === 'pair') {
    if (
      !ownKeys(value, ['operation', 'code', 'device_name']) ||
      typeof value.code !== 'string' ||
      !/^[A-Za-z2-7]{12}$/.test(value.code) ||
      typeof value.device_name !== 'string' ||
      !value.device_name.trim() ||
      Array.from(value.device_name).length > 64
    )
      throw invalidRequest();
  } else if (operation === 'delete_session') {
    if (!ownKeys(value, ['operation', 'session_id']) || !uuid(value.session_id))
      throw invalidRequest();
  } else if (operation === 'job' || operation === 'cancel') {
    if (!ownKeys(value, ['operation', 'job_id']) || !uuid(value.job_id)) throw invalidRequest();
  } else if (operation === 'translate') {
    if (
      !ownKeys(value, ['operation', 'session_id', 'client_request_id', 'request']) ||
      !uuid(value.session_id) ||
      !uuid(value.client_request_id) ||
      !isRecord(value.request) ||
      !ownKeys(value.request, [
        'text',
        'source_language',
        'target_language',
        'style',
        'domain',
        'task_mode',
      ])
    )
      throw invalidRequest();
    const request = value.request;
    if (
      typeof request.text !== 'string' ||
      !request.text.trim() ||
      Array.from(request.text).length > 4000 ||
      !['source_language', 'target_language'].every(
        (key) =>
          typeof request[key] === 'string' &&
          Boolean(request[key]) &&
          String(request[key]).length <= 64,
      ) ||
      !['standard', 'formal', 'colloquial'].includes(String(request.style)) ||
      !['general', 'technology', 'business', 'finance', 'legal', 'medical', 'academic'].includes(
        String(request.domain),
      ) ||
      !['auto', 'translate', 'annotate_code', 'annotate_special'].includes(
        String(request.task_mode),
      )
    )
      throw invalidRequest();
  } else throw invalidRequest();
  return JSON.parse(JSON.stringify(value)) as AndroidApiOperation;
}

/** Java 端必须先删除敏感字段；这里拒绝违反协议的宿主响应，不将其透传给 UI。 */
export function assertPublicResponse(value: unknown): void {
  const secret = /^(access_token|refresh_token|token|token_type|authorization|bearer_token)$/i;
  let count = 0;
  function visit(item: unknown, depth: number): void {
    if (++count > 20_000 || depth > 16) throw invalidRequest();
    if (Array.isArray(item)) item.forEach((child) => visit(child, depth + 1));
    else if (isRecord(item)) {
      for (const [key, child] of Object.entries(item)) {
        if (secret.test(key)) throw invalidRequest();
        visit(child, depth + 1);
      }
    }
  }
  visit(value, 0);
}
