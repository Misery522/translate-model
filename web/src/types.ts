import type { components } from './api.generated';

// 线上的数据结构只从后端 OpenAPI 派生；下面仅保留浏览器显示状态。
export type TranslationRequest = components['schemas']['AgentRequest'];
export type TaskMode = TranslationRequest['task_mode'];
export type Options = Omit<TranslationRequest, 'text' | 'source_language'>;
export type AgentResult = components['schemas']['AgentResult'];
export type ApiProblem = Omit<components['schemas']['ApiErrorView'], 'request_id'> &
  Partial<Pick<components['schemas']['ApiErrorView'], 'request_id'>>;
export type AuthView = components['schemas']['AuthView'];
export type PairView = components['schemas']['PairView'];
export type DeviceAuth = Omit<AuthView, 'auth_mode' | 'csrf_token'> & {
  auth_mode: 'cookie';
  csrf_token: string;
};
export type WorkSession = components['schemas']['SessionView'];
export type Job = components['schemas']['JobView'];
export interface Turn {
  id: string;
  request: TranslationRequest;
  status: 'pending' | 'done' | 'error' | 'cancelled';
  result?: AgentResult;
  error?: string;
}
