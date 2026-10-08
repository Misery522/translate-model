import { useCallback, useEffect, useRef, useState } from "react";
import App from "../../web/src/App";
import { AndroidTranslationApi } from "../../web/src/androidApi";
import type {
  AndroidBackendStatus,
  AndroidInvoker,
} from "../../web/src/androidProtocol";
import { ApiError } from "../../web/src/api";
import { Pet } from "../../web/src/Pet";

type Phase = "checking" | "unconfigured" | "saving" | "ready" | "error";
const errorMessage = (error: unknown) =>
  error instanceof ApiError
    ? error.problem.message
    : "原生连接暂不可用，请重新读取状态。此页面不能作为普通网页使用。";

export default function NativeApp({ invoke }: { invoke: AndroidInvoker }) {
  const [api] = useState(() => new AndroidTranslationApi(invoke));
  const [origin, setOrigin] = useState("");
  const [phase, setPhase] = useState<Phase>("checking");
  const [status, setStatus] = useState<AndroidBackendStatus | null>(null);
  const [notice, setNotice] = useState("正在读取原生连接状态…");
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const readStatus = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    controller.current?.abort();
    const operation = new AbortController();
    controller.current = operation;
    const current = ++sequence.current;
    setPhase("checking");
    setStatus(null);
    setNotice("正在读取原生连接状态…");
    try {
      const value = await api.backendStatus(operation.signal);
      if (operation.signal.aborted || sequence.current !== current) return;
      setOrigin(value.origin ?? "");
      setStatus(value);
      setRevision((previous) => previous + 1);
      setPhase(value.origin ? "ready" : "unconfigured");
      setNotice(
        value.origin
          ? "地址已明确配置。配对后即可开始文字翻译。"
          : "尚未设置私人电脑地址。",
      );
    } catch (error) {
      if (operation.signal.aborted || sequence.current !== current) return;
      setPhase("error");
      setNotice(errorMessage(error));
    } finally {
      if (sequence.current === current) busy.current = false;
    }
  }, [api]);

  useEffect(() => {
    void readStatus();
    return () => {
      sequence.current += 1;
      controller.current?.abort();
      busy.current = false;
    };
  }, [readStatus]);

  async function configure() {
    if (busy.current) return;
    busy.current = true;
    controller.current?.abort();
    const operation = new AbortController();
    controller.current = operation;
    const current = ++sequence.current;
    // 即使保存同一地址，也先卸载旧对话；失效或迟到的响应不可恢复它。
    setStatus(null);
    setPhase("saving");
    setNotice("正在设置地址；旧内容已清空。");
    try {
      const value = await api.configureBackend(origin, operation.signal);
      if (operation.signal.aborted || sequence.current !== current) return;
      setOrigin(value.origin ?? "");
      setStatus(value);
      setRevision((previous) => previous + 1);
      setPhase("ready");
      setNotice("地址已明确配置。请使用电脑的新配对码重新配对。");
    } catch (error) {
      if (operation.signal.aborted || sequence.current !== current) return;
      setPhase("error");
      setNotice(errorMessage(error));
    } finally {
      if (sequence.current === current) busy.current = false;
    }
  }

  const waiting = phase === "checking" || phase === "saving";
  return (
    <div className="native-page">
      <section className="native-connection" aria-labelledby="native-title">
        <div className="native-heading">
          <Pet />
          <div>
            <h1 id="native-title">译境 · Android 私人试用</h1>
            <p>独立 App，连接你的电脑模型。当前仅支持前台文字翻译。</p>
          </div>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void configure();
          }}
        >
          <label htmlFor="native-origin">私人电脑服务地址</label>
          <div className="native-origin-controls">
            <input
              id="native-origin"
              type="text"
              inputMode="url"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              disabled={waiting}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="https://设备名.私人网络名.ts.net"
              maxLength={1024}
              aria-describedby="native-address-help"
            />
            <button
              className="primary-button"
              disabled={waiting || !origin}
              type="submit"
            >
              {phase === "saving" ? "正在设置…" : "保存地址并重新配对"}
            </button>
          </div>
          <p id="native-address-help" className="small-note">
            从自己的电脑复制私人 Serve 地址；只接受 HTTPS
            源，不含路径。域名后缀不是身份认证。
            保存任何地址（包括同一地址）都会清空当前内容和配对。
          </p>
        </form>
        <p className="native-status" role="status" aria-live="polite">
          {notice}
        </p>
        {phase === "error" && (
          <button className="text-button" onClick={() => void readStatus()}>
            重新读取连接状态
          </button>
        )}
        <p className="native-privacy">
          令牌只保存在原生进程内存；原文和译文不持久保存。退到后台会清空并需要重新配对。
          电脑、Ollama、私人 API 和两端 Tailscale
          需保持在线；这不是手机离线模型。
        </p>
      </section>
      {phase === "ready" && status?.origin && (
        <App key={revision} api={api} platform="android" />
      )}
    </div>
  );
}
