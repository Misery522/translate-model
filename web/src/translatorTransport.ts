import type { DeviceAuth, Job, TranslationRequest, WorkSession } from './types';

/** 共享状态机只依赖业务操作；地址、令牌和平台能力留在对应宿主。 */
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
