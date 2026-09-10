import type { DeviceAuth, Job, TranslationRequest, WorkSession } from './types';

/** 共享状态机唯一依赖的传输接口；不包含 URL、令牌、窗口或模型调用能力。 */
export interface TranslatorTransport {
  auth(signal?: AbortSignal): Promise<DeviceAuth>;
  pair(code: string, signal?: AbortSignal): Promise<DeviceAuth>;
  logout(csrf: string | null, signal?: AbortSignal): Promise<void>;
  createSession(csrf: string | null, signal?: AbortSignal): Promise<WorkSession>;
  deleteSession(id: string, csrf: string | null, signal?: AbortSignal): Promise<void>;
  leaveSession(id: string, csrf: string | null): void;
  translate(
    session: string,
    clientRequestId: string,
    request: TranslationRequest,
    csrf: string | null,
    signal?: AbortSignal,
  ): Promise<Job>;
  job(id: string, signal?: AbortSignal): Promise<Job>;
  cancel(id: string, csrf: string | null, signal?: AbortSignal): Promise<Job>;
}
