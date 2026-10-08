import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NativeApp from "./NativeApp";
import type {
  AndroidBridgeCommand,
  AndroidInvoker,
} from "../../web/src/androidProtocol";

const origin = "https://trusted-computer.private-network.ts.net";
const auth = {
  device_id: "device-1",
  device_name: "译境 Android",
  expires_at: "2099-01-01",
  auth_mode: "bearer",
  csrf_token: null,
};
function fixture(initialOrigin: string | null = null) {
  let generation = 0;
  let configured = initialOrigin;
  let paired = false;
  const invoke = vi.fn<AndroidInvoker>(async (command) => {
    if (command.command === "backend_status")
      return { origin: configured, paired, generation };
    if (command.command === "configure_backend") {
      configured = command.origin;
      paired = false;
      generation += 1;
      return { origin: configured, paired, generation };
    }
    if (command.request.operation === "auth") {
      if (!paired)
        throw { code: "PAIRING_REQUIRED", status: 401, retryable: false };
      return { status: 200, body: auth, generation };
    }
    if (command.request.operation === "pair") {
      paired = true;
      generation += 1;
      return { status: 201, body: auth, generation };
    }
    if (command.request.operation === "create_session")
      return {
        status: 201,
        generation,
        body: {
          session_id: "11111111-1111-4111-8111-111111111111",
          generation: 0,
          expires_at: "2099-01-01",
        },
      };
    throw { code: "INVALID_REQUEST" };
  });
  return invoke;
}
const operations = (invoke: ReturnType<typeof fixture>) =>
  invoke.mock.calls.map(([command]) =>
    command.command === "api_request"
      ? command.request.operation
      : command.command,
  );
function save() {
  fireEvent.change(screen.getByLabelText("私人电脑服务地址"), {
    target: { value: origin },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存地址并重新配对" }));
}

describe("Android 本地页面", () => {
  it("未明确配置地址时只读原生状态，不发起认证或真实 JavaScript 网络", async () => {
    const invoke = fixture();
    const network = vi.spyOn(window, "fetch");
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(<NativeApp invoke={invoke} />);
    await screen.findByText("尚未设置私人电脑地址。");
    expect(operations(invoke)).toEqual(["backend_status"]);
    expect(network).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("12 位配对码")).not.toBeInTheDocument();
    expect(screen.getByText(/令牌只保存在原生进程内存/)).toBeInTheDocument();
  });

  it("只接受私人 Serve 源；拒绝路径、HTTP 和无效来源，不调用宿主设置", async () => {
    const invoke = fixture();
    render(<NativeApp invoke={invoke} />);
    await screen.findByText("尚未设置私人电脑地址。");
    fireEvent.change(screen.getByLabelText("私人电脑服务地址"), {
      target: { value: "http://127.0.0.1:8766" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存地址并重新配对" }));
    await screen.findByText(/请输入私人 Serve 的 HTTPS 源地址/);
    expect(operations(invoke)).toEqual(["backend_status"]);
    expect(screen.queryByLabelText("12 位配对码")).not.toBeInTheDocument();
  });

  it("配置成功才挂载共享翻译界面；配对采用原生 Bearer 而非网页 Cookie", async () => {
    const invoke = fixture();
    render(<NativeApp invoke={invoke} />);
    await screen.findByText("尚未设置私人电脑地址。");
    save();
    await screen.findByLabelText("12 位配对码");
    expect(operations(invoke)).toEqual([
      "backend_status",
      "configure_backend",
      "auth",
    ]);
    expect(
      screen.getByText(
        "凭据只在原生内存中保存。退到后台会清空内容，并需要重新配对。",
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("12 位配对码"), {
      target: { value: "ABCDEFGH2345" },
    });
    fireEvent.click(screen.getByRole("button", { name: /连接，开始翻译/ }));
    await screen.findByLabelText("原文");
    expect(operations(invoke)).toContain("pair");
    expect(operations(invoke)).toContain("create_session");
  });

  it("保存同一地址也立即卸载旧对话和草稿，并重新配对", async () => {
    const invoke = fixture(origin);
    render(<NativeApp invoke={invoke} />);
    await screen.findByLabelText("12 位配对码");
    fireEvent.change(screen.getByLabelText("12 位配对码"), {
      target: { value: "ABCDEFGH2345" },
    });
    fireEvent.click(screen.getByRole("button", { name: /连接，开始翻译/ }));
    await screen.findByLabelText("原文");
    fireEvent.change(screen.getByLabelText("原文"), {
      target: { value: "private draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存地址并重新配对" }));
    await screen.findByLabelText("12 位配对码");
    expect(screen.queryByLabelText("原文")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("private draft")).not.toBeInTheDocument();
    expect(screen.getByLabelText("12 位配对码")).toHaveValue("");
    expect(
      operations(invoke).filter((op) => op === "configure_backend"),
    ).toHaveLength(1);
  });

  it("设置期间禁用重复保存，失败只显示固定可恢复提示，不恢复旧界面", async () => {
    let reject!: (reason: unknown) => void;
    const pending = new Promise((_, fail) => {
      reject = fail;
    });
    const invoke = fixture();
    const handler = invoke.getMockImplementation()!;
    invoke.mockImplementation((command: AndroidBridgeCommand) =>
      command.command === "configure_backend" ? pending : handler(command),
    );
    render(<NativeApp invoke={invoke} />);
    await screen.findByText("尚未设置私人电脑地址。");
    save();
    expect(screen.getByRole("button", { name: "正在设置…" })).toBeDisabled();
    await act(async () =>
      reject({ code: "PRIVATE_URL", message: "secret-origin token" }),
    );
    await screen.findByText("连接未完成；请求可能已送达，尚未确认服务端停止。");
    expect(screen.queryByText(/secret-origin token/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("12 位配对码")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新读取连接状态" }),
    ).toBeEnabled();
  });

  it("卸载后迟到原生状态不影响新页面", async () => {
    let resolve!: (value: unknown) => void;
    const old = vi.fn<AndroidInvoker>(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const first = render(<NativeApp invoke={old} />);
    await waitFor(() => expect(old).toHaveBeenCalledTimes(1));
    first.unmount();
    const invoke = fixture();
    render(<NativeApp invoke={invoke} />);
    await screen.findByText("尚未设置私人电脑地址。");
    await act(async () => resolve({ origin, paired: true, generation: 20 }));
    await waitFor(() =>
      expect(screen.queryByLabelText("12 位配对码")).not.toBeInTheDocument(),
    );
    expect(operations(invoke)).toEqual(["backend_status"]);
  });

  it("配置地址后，迟到的旧身份不能创建会话或恢复旧对话", async () => {
    let completeOldAuth!: (value: unknown) => void;
    const invoke = fixture(origin);
    const handler = invoke.getMockImplementation()!;
    let firstAuth = true;
    invoke.mockImplementation((command) => {
      if (
        command.command === "api_request" &&
        command.request.operation === "auth" &&
        firstAuth
      ) {
        firstAuth = false;
        return new Promise((resolve) => {
          completeOldAuth = resolve;
        });
      }
      return handler(command);
    });
    render(<NativeApp invoke={invoke} />);
    await waitFor(() => expect(operations(invoke)).toContain("auth"));
    fireEvent.click(screen.getByRole("button", { name: "保存地址并重新配对" }));
    await screen.findByLabelText("12 位配对码");
    await act(async () =>
      completeOldAuth({ status: 200, generation: 0, body: auth }),
    );
    expect(screen.queryByLabelText("原文")).not.toBeInTheDocument();
    expect(operations(invoke)).not.toContain("create_session");
    expect(screen.getByLabelText("12 位配对码")).toHaveValue("");
  });
});
