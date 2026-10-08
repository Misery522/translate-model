import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import NativeApp from "./NativeApp";
import { createNativeBridge } from "./nativeBridge";
import "../../web/src/styles.css";
import "./native.css";

const root = createRoot(document.getElementById("root")!);
if (
  !window.YijingNative ||
  typeof window.YijingNative.postMessage !== "function"
) {
  root.render(
    <main className="native-unavailable">
      <h1>请从译境 Android App 打开</h1>
      <p>此页面需要安全的原生连接桥，不能作为普通浏览器网页使用。</p>
      <p>
        如果 App 中出现此提示，请更新 Android System WebView
        后重试；不会降级到不安全连接。
      </p>
    </main>,
  );
} else {
  const bridge = createNativeBridge();
  // 宿主退到后台会销毁敏感页面；页面结束同时释放全部 JS 等待记录。
  window.addEventListener("pagehide", bridge.dispose, { once: true });
  root.render(
    <StrictMode>
      <NativeApp invoke={bridge.invoke} />
    </StrictMode>,
  );
}
