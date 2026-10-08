import { describe, expect, it, vi } from "vitest";
import { createNativeBridge } from "./nativeBridge";
import type { NativeMessagePort } from "./nativeBridge";

function fixture() {
  const port: NativeMessagePort = { postMessage: vi.fn(), onmessage: null };
  const bridge = createNativeBridge(port);
  const posted = () =>
    JSON.parse(vi.mocked(port.postMessage).mock.calls.at(-1)![0]);
  const respond = (response: unknown) =>
    port.onmessage?.({ data: JSON.stringify(response) });
  return { port, bridge, posted, respond };
}

describe("Android 主框架 WebMessage 桥", () => {
  it("只发送安全 UUID 和纯数据白名单命令，并按 id 接收响应", async () => {
    const { bridge, posted, respond } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    const request = posted();
    expect(request).toEqual({
      id: expect.any(String),
      payload: { command: "backend_status" },
    });
    expect(request.id).toMatch(/^[0-9a-f-]{36}$/);
    respond({
      id: request.id,
      data: { origin: null, paired: false, generation: 0 },
    });
    await expect(result).resolves.toEqual({
      origin: null,
      paired: false,
      generation: 0,
    });
    bridge.dispose();
  });

  it("普通浏览器缺少原生桥时失败，不降级为 JavaScript 网络请求", async () => {
    const network = vi.spyOn(window, "fetch");
    const bridge = createNativeBridge(undefined);
    await expect(
      bridge.invoke({ command: "backend_status" }),
    ).rejects.toMatchObject({
      code: "NATIVE_BRIDGE_UNAVAILABLE",
    });
    expect(network).not.toHaveBeenCalled();
  });

  it("未知或重复响应 id 不会恢复已结束的请求", async () => {
    const { bridge, posted, respond } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    const request = posted();
    let settled = false;
    void result.finally(() => {
      settled = true;
    });
    respond({ id: "11111111-1111-4111-8111-111111111111", data: {} });
    await Promise.resolve();
    expect(settled).toBe(false);
    respond({ id: request.id, data: { paired: false } });
    await expect(result).resolves.toEqual({ paired: false });
    respond({ id: request.id, error: { code: "TLS_REJECTED" } });
    bridge.dispose();
  });

  it.each([
    (id: string) => ({ id, data: {}, error: { code: "TLS_REJECTED" } }),
    (id: string) => ({ id, data: {}, additional: "secret" }),
    (id: string) => ({ id, data: { access_token: "must-not-reach-ui" } }),
    (id: string) => ({
      id,
      error: { code: "TLS_REJECTED", message: "private-origin secret" },
    }),
  ])("拒绝结构畸形或带凭据的已知回包", async (response) => {
    const { bridge, posted, respond } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    respond(response(posted().id));
    await expect(result).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    bridge.dispose();
  });

  it("错误只透传固定代码、有效状态和布尔重试标记", async () => {
    const { bridge, posted, respond } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    respond({
      id: posted().id,
      error: { code: "TLS_REJECTED", status: 502, retryable: false },
    });
    await expect(result).rejects.toEqual({
      code: "TLS_REJECTED",
      status: 502,
      retryable: false,
    });
    const unknown = bridge.invoke({ command: "backend_status" });
    respond({ id: posted().id, error: { code: "PRIVATE_SECRET" } });
    await expect(unknown).rejects.toEqual({
      code: "NETWORK_UNCONFIRMED",
      retryable: true,
    });
    bridge.dispose();
  });

  it("20 秒等待上限后删除等待记录，迟到响应不能复活", async () => {
    vi.useFakeTimers();
    const { bridge, posted, respond } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    const assertion = expect(result).rejects.toMatchObject({
      code: "NETWORK_UNCONFIRMED",
    });
    const id = posted().id;
    await vi.advanceTimersByTimeAsync(20_000);
    await assertion;
    respond({ id, data: { generation: 0 } });
    expect(bridge.pendingCount).toBe(0);
    bridge.dispose();
  });

  it("128 条等待上限，不淘汰仍在运行的消息", async () => {
    const { bridge, port } = fixture();
    const pending = Array.from({ length: 128 }, () =>
      bridge.invoke({ command: "backend_status" }),
    );
    const assertions = pending.map((promise) =>
      expect(promise).rejects.toMatchObject({ code: "STALE_OPERATION" }),
    );
    await expect(
      bridge.invoke({ command: "backend_status" }),
    ).rejects.toMatchObject({ code: "RATE_LIMITED" });
    expect(port.postMessage).toHaveBeenCalledTimes(128);
    bridge.dispose();
    await Promise.all(assertions);
    expect(bridge.pendingCount).toBe(0);
  });

  it("页面关闭或 dispose 结束全部等待，之后不再调用原生", async () => {
    const { bridge, posted, respond, port } = fixture();
    const result = bridge.invoke({ command: "backend_status" });
    const id = posted().id;
    const assertion = expect(result).rejects.toMatchObject({
      code: "STALE_OPERATION",
    });
    bridge.dispose();
    await assertion;
    respond({ id, data: { paired: true } });
    await expect(
      bridge.invoke({ command: "backend_status" }),
    ).rejects.toMatchObject({ code: "STALE_OPERATION" });
    expect(port.postMessage).toHaveBeenCalledTimes(1);
    expect(port.onmessage).toBeNull();
  });

  it("发出前复制命令；拒绝任意 URL、无界代次和额外字段", async () => {
    const { bridge, port } = fixture();
    for (const command of [
      { command: "fetch", url: "https://example.com" },
      { command: "backend_status", extra: true },
      {
        command: "api_request",
        generation: -1,
        request: { operation: "health" },
      },
    ])
      await expect(bridge.invoke(command as never)).rejects.toMatchObject({
        code: "INVALID_REQUEST",
      });
    expect(port.postMessage).not.toHaveBeenCalled();
    bridge.dispose();
  });

  it("原生 postMessage 抛出的错误不得泄露地址、配对码或令牌", async () => {
    const { bridge, port } = fixture();
    vi.mocked(port.postMessage).mockImplementation(() => {
      throw new Error("private-origin token pairing-code");
    });
    await expect(bridge.invoke({ command: "backend_status" })).rejects.toEqual({
      code: "NETWORK_UNCONFIRMED",
      retryable: true,
    });
    expect(bridge.pendingCount).toBe(0);
    bridge.dispose();
  });
});
