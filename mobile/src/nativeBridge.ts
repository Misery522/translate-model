import {
  assertPublicResponse,
  isRecord,
  normalizeAndroidOrigin,
  validateAndroidOperation,
} from "../../web/src/androidProtocol";
import type {
  AndroidBridgeCommand,
  AndroidInvoker,
} from "../../web/src/androidProtocol";
import { createRequestId } from "../../web/src/requestId";

export interface NativeMessagePort {
  postMessage(message: string): void;
  onmessage: ((event: { data: unknown }) => void) | null;
}

declare global {
  interface Window {
    /** 仅由精确本地源、主框架的 Android WebMessageListener 注入。 */
    YijingNative?: NativeMessagePort;
  }
}

interface BridgeProblem {
  code: string;
  status?: number;
  retryable?: boolean;
}
interface Pending {
  timer: ReturnType<typeof setTimeout>;
  resolve: (value: unknown) => void;
  reject: (error: BridgeProblem) => void;
}
const codes = new Set([
  "INVALID_REQUEST",
  "FORBIDDEN",
  "INVALID_RESPONSE",
  "STALE_OPERATION",
  "PAIRING_REQUIRED",
  "NETWORK_UNCONFIRMED",
  "REDIRECT_BLOCKED",
  "TLS_REJECTED",
  "ACCESS_DENIED",
  "NOT_FOUND",
  "CONFLICT",
  "RATE_LIMITED",
  "SERVICE_UNAVAILABLE",
  "REQUEST_TOO_LARGE",
  "REQUEST_REJECTED",
  "BACKEND_NOT_CONFIGURED",
]);
const ownKeys = (value: Record<string, unknown>, fields: string[]) =>
  Object.keys(value).length === fields.length &&
  fields.every((field) => Object.hasOwn(value, field));
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const problem = (code: string, retryable = false): BridgeProblem => ({
  code,
  retryable,
});

function validatedCommand(value: AndroidBridgeCommand): AndroidBridgeCommand {
  if (!isRecord(value)) throw problem("INVALID_REQUEST");
  if (value.command === "backend_status" && ownKeys(value, ["command"]))
    return { command: "backend_status" };
  if (
    value.command === "configure_backend" &&
    ownKeys(value, ["command", "origin"])
  ) {
    if (typeof value.origin !== "string") throw problem("INVALID_REQUEST");
    try {
      return {
        command: "configure_backend",
        origin: normalizeAndroidOrigin(value.origin),
      };
    } catch {
      throw problem("INVALID_REQUEST");
    }
  }
  if (
    value.command === "api_request" &&
    ownKeys(value, ["command", "generation", "request"]) &&
    Number.isSafeInteger(value.generation) &&
    Number(value.generation) >= 0
  ) {
    try {
      return {
        command: "api_request",
        generation: Number(value.generation),
        request: validateAndroidOperation(value.request),
      };
    } catch {
      throw problem("INVALID_REQUEST");
    }
  }
  throw problem("INVALID_REQUEST");
}

function responseError(value: unknown): BridgeProblem {
  if (
    !isRecord(value) ||
    !Object.hasOwn(value, "code") ||
    typeof value.code !== "string" ||
    !Object.keys(value).every((key) =>
      ["code", "status", "retryable"].includes(key),
    ) ||
    (Object.hasOwn(value, "status") &&
      (!Number.isInteger(value.status) ||
        Number(value.status) < 400 ||
        Number(value.status) > 599)) ||
    (Object.hasOwn(value, "retryable") && typeof value.retryable !== "boolean")
  )
    return problem("INVALID_RESPONSE");
  if (!codes.has(value.code)) return problem("NETWORK_UNCONFIRMED", true);
  return {
    code: value.code,
    ...(Object.hasOwn(value, "status") ? { status: Number(value.status) } : {}),
    ...(Object.hasOwn(value, "retryable")
      ? { retryable: value.retryable as boolean }
      : {}),
  };
}

/** 没有 fetch、旧式 JavascriptInterface 或其他网络/桥接降级入口。 */
export function createNativeBridge(
  port: NativeMessagePort | undefined = window.YijingNative,
) {
  const pending = new Map<string, Pending>();
  let disposed = false;
  const finish = (id: string, action: (request: Pending) => void) => {
    const request = pending.get(id);
    if (!request) return;
    pending.delete(id);
    clearTimeout(request.timer);
    action(request);
  };
  const receive = (event: { data: unknown }) => {
    // 有界 JSON 消息与未知 id 均不形成日志或新的等待记录。
    if (typeof event.data !== "string" || event.data.length > 1_048_576) return;
    let message: unknown;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!isRecord(message) || !uuid(message.id) || !pending.has(message.id))
      return;
    const id = message.id;
    const hasData = Object.hasOwn(message, "data");
    const hasError = Object.hasOwn(message, "error");
    if (
      hasData === hasError ||
      !ownKeys(message, ["id", hasData ? "data" : "error"])
    ) {
      finish(id, (request) => request.reject(problem("INVALID_RESPONSE")));
      return;
    }
    if (hasError) {
      finish(id, (request) => request.reject(responseError(message.error)));
      return;
    }
    try {
      assertPublicResponse(message.data);
      finish(id, (request) => request.resolve(message.data));
    } catch {
      finish(id, (request) => request.reject(problem("INVALID_RESPONSE")));
    }
  };
  if (port) port.onmessage = receive;

  const invoke: AndroidInvoker = (input) => {
    if (disposed) return Promise.reject(problem("STALE_OPERATION"));
    if (!port || typeof port.postMessage !== "function")
      return Promise.reject(problem("NATIVE_BRIDGE_UNAVAILABLE"));
    if (pending.size >= 128)
      return Promise.reject(problem("RATE_LIMITED", true));
    let payload: AndroidBridgeCommand;
    let id: string;
    try {
      payload = validatedCommand(input);
      id = createRequestId();
      if (!uuid(id) || pending.has(id)) throw problem("INVALID_REQUEST");
    } catch {
      return Promise.reject(problem("INVALID_REQUEST"));
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () =>
          finish(id, (request) =>
            request.reject(problem("NETWORK_UNCONFIRMED", true)),
          ),
        20_000,
      );
      pending.set(id, { timer, resolve, reject });
      try {
        port.postMessage(JSON.stringify({ id, payload }));
      } catch {
        finish(id, (request) =>
          request.reject(problem("NETWORK_UNCONFIRMED", true)),
        );
      }
    });
  };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    if (port?.onmessage === receive) port.onmessage = null;
    for (const id of pending.keys())
      finish(id, (request) => request.reject(problem("STALE_OPERATION")));
  };
  return {
    invoke,
    dispose,
    get pendingCount() {
      return pending.size;
    },
  };
}
