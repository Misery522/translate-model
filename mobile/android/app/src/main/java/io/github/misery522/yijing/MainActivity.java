package io.github.misery522.yijing;

import android.app.Activity;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.view.WindowInsets;
import android.view.WindowManager;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import io.github.misery522.yijing.core.BridgeFailure;
import io.github.misery522.yijing.core.NativeTranslatorCore;
import io.github.misery522.yijing.host.BrowserPolicy;
import io.github.misery522.yijing.host.BridgeReplies;
import io.github.misery522.yijing.host.HttpsTransport;
import io.github.misery522.yijing.host.StrictJson;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** APK 内置页面的唯一原生桥；无通用 HTTP 插件、文件权限或旧式 JS 接口。 */
public final class MainActivity extends Activity {
    private final HttpsTransport transport = new HttpsTransport();
    private final NativeTranslatorCore core = new NativeTranslatorCore(transport);
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(8), new ThreadPoolExecutor.AbortPolicy());
    private final Set<String> pending = new HashSet<>();
    private WebView webView;
    private boolean foreground;
    private boolean suspended;
    private long pageEpoch;

    @Override
    protected void onCreate(Bundle ignoredState) {
        // 不恢复 Bundle 中的网页、译文或身份。
        super.onCreate(null);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        if (Build.VERSION.SDK_INT >= 29) {
            android.view.contentcapture.ContentCaptureManager capture = getSystemService(android.view.contentcapture.ContentCaptureManager.class);
            if (capture != null) capture.setContentCaptureEnabled(false);
        }
        try {
            WebView.setWebContentsDebuggingEnabled(false);
            if (!BrowserPolicy.supportedUserAgent(WebSettings.getDefaultUserAgent(this))
                || !WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                failurePage("请更新 Android System WebView 至 Chromium 111 或更高，且支持安全消息桥。未识别的 WebView 暂不能使用。");
                return;
            }
            createBrowser();
        } catch (Exception error) {
            failurePage("安全界面初始化失败，请更新系统 WebView 后重新打开。未降级为旧式桥。");
        }
    }

    @android.annotation.SuppressLint("SetJavaScriptEnabled")
    private void createBrowser() {
        WebView view = new WebView(this);
        webView = view;
        view.setSaveEnabled(false);
        view.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        if (Build.VERSION.SDK_INT >= 30)
            view.setImportantForContentCapture(android.view.View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS);
        CookieManager.getInstance().setAcceptCookie(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, false);
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        view.setDownloadListener((url, agent, disposition, mime, length) -> {});
        view.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) { callback.invoke(origin, false, false); }
            @Override public boolean onShowFileChooser(WebView browser, ValueCallback<Uri[]> callback, FileChooserParams params) { callback.onReceiveValue(null); return true; }
            @Override public boolean onConsoleMessage(android.webkit.ConsoleMessage message) { return true; }
        });
        WebViewAssetLoader assets = new WebViewAssetLoader.Builder().setDomain("localhost").setHttpAllowed(false)
            .addPathHandler("/app/", path -> localAsset(path)).build();
        view.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView browser, WebResourceRequest request) {
                if (!"GET".equals(request.getMethod()) || BrowserPolicy.asset(request.getUrl().toString()) == null)
                    return blocked(403);
                WebResourceResponse response = assets.shouldInterceptRequest(request.getUrl());
                return response == null ? blocked(404) : response;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView browser, WebResourceRequest request) {
                return !request.isForMainFrame() || !"GET".equals(request.getMethod()) || !BrowserPolicy.entry(request.getUrl().toString());
            }
            @Override public void onPageStarted(WebView browser, String url, android.graphics.Bitmap favicon) {
                pageEpoch++;
                pending.clear();
                if (BrowserPolicy.entry(url)) return;
                if (!"about:blank".equals(url)) failurePage("已阻止非本地界面导航，请重新打开译境。");
            }
            @Override public boolean onRenderProcessGone(WebView browser, RenderProcessGoneDetail detail) {
                failurePage("系统网页引擎已退出。身份和内容已清空，请重新打开译境。"); return true;
            }
        });
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
        WebViewCompat.addWebMessageListener(view, "YijingNative", Collections.singleton(BrowserPolicy.ORIGIN),
            (browser, message, sourceOrigin, mainFrame, reply) -> {
                if (!foreground || browser != webView || !mainFrame
                    || !BrowserPolicy.ORIGIN.equals(sourceOrigin.toString()) || !BrowserPolicy.entry(browser.getUrl())
                    || message.getType() != WebMessageCompat.TYPE_STRING) return;
                String data = message.getData();
                if (data == null || data.length() > NativeTranslatorCore.REQUEST_LIMIT_BYTES) return;
                try {
                    Map<String, Object> envelope = object(StrictJson.parse(data));
                    if (envelope.size() != 2 || !envelope.containsKey("payload") || !envelope.containsKey("id")) return;
                    String id = envelope.get("id") instanceof String ? (String) envelope.get("id") : "";
                    if (!id.matches("[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}") || pending.contains(id)) return;
                    Map<String, Object> command = object(envelope.get("payload"));
                    if (pending.size() >= 32) { safePost(reply, StrictJson.stringify(errorReply(id, "RATE_LIMITED", 0, true))); return; }
                    long epoch = pageEpoch;
                    pending.add(id);
                    Runnable operation = () -> {
                        Map<String, Object> response = null;
                        Map<String, Object> error = null;
                        try { response = core.invoke(command); }
                        catch (BridgeFailure failure) { error = errorReply(id, failure.code, failure.status, failure.retryable); }
                        catch (Exception failure) { error = errorReply(id, "INVALID_REQUEST", 0, false); }
                        Map<String, Object> result = response;
                        Map<String, Object> problem = error;
                        String encoded;
                        try {
                            if (problem != null) encoded = StrictJson.stringify(problem);
                            else {
                                encoded = BridgeReplies.success(id, result);
                            }
                        } catch (Exception failure) {
                            encoded = StrictJson.stringify(errorReply(id, "INVALID_RESPONSE", 0, false));
                            problem = errorReply(id, "INVALID_RESPONSE", 0, false);
                        }
                        String outgoing = encoded;
                        boolean failed = problem != null;
                        runOnUiThread(() -> {
                            if (!foreground || webView != browser || pageEpoch != epoch || !pending.remove(id)) return;
                            try {
                                if (failed) safePost(reply, outgoing);
                                else if (!core.deliverIfCurrent(result, () -> safePost(reply, outgoing)))
                                    safePost(reply, StrictJson.stringify(errorReply(id, "STALE_OPERATION", 0, false)));
                            } catch (Exception ignored) { /* 网页已失效；不把桥异常变成主线程崩溃。 */ }
                        });
                    };
                    // 配置/读状态不联网，在 UI 串行重置，避免队列延迟后恢复旧配置。
                    if ("configure_backend".equals(command.get("command")) || "backend_status".equals(command.get("command"))) operation.run();
                    else {
                        try { workers.execute(operation); }
                        catch (java.util.concurrent.RejectedExecutionException error) {
                            pending.remove(id); safePost(reply, StrictJson.stringify(errorReply(id, "RATE_LIMITED", 0, true)));
                        }
                    }
                } catch (Exception ignored) { /* 无有效 ID 的非法消息不反射内容。 */ }
            });
        } else throw new IllegalStateException("SAFE_BRIDGE_REQUIRED");
        LinearLayout container = new LinearLayout(this); container.setOrientation(LinearLayout.VERTICAL);
        android.widget.Button about = new android.widget.Button(this); about.setText(R.string.about_licenses);
        about.setOnClickListener(button -> showLicenses());
        container.addView(about, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        container.addView(view, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(container);
        view.setOnApplyWindowInsetsListener((content, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                content.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            }
            return insets;
        });
        view.loadUrl(BrowserPolicy.ENTRY);
    }

    private static void safePost(androidx.webkit.JavaScriptReplyProxy reply, String outgoing) {
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            try { reply.postMessage(outgoing); } catch (Exception ignored) { /* 已失效的页面。 */ }
        }
    }

    private void showLicenses() {
        StringBuilder content = new StringBuilder(getString(R.string.native_privacy));
        for (String name : new String[] {"THIRD_PARTY_ANDROID_NOTICES.txt", "THIRD_PARTY_LICENSES.txt", "LICENSE.txt"}) {
            try (java.io.InputStream input = getAssets().open("public/notices/" + name)) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int count;
                while ((count = input.read(buffer)) >= 0) {
                    if (bytes.size() + count > 131072) throw new IOException();
                    bytes.write(buffer, 0, count);
                }
                content.append("\n\n").append(new String(bytes.toByteArray(), java.nio.charset.StandardCharsets.UTF_8));
            } catch (IOException error) { content.append("\n\n").append(getString(R.string.license_unavailable)); }
        }
        TextView text = new TextView(this); text.setText(content.toString()); text.setTextSize(14); text.setPadding(24, 24, 24, 24);
        android.widget.ScrollView scroll = new android.widget.ScrollView(this); scroll.addView(text);
        new android.app.AlertDialog.Builder(this).setTitle(R.string.about_licenses).setView(scroll).setPositiveButton(android.R.string.ok, null).show();
    }

    private WebResourceResponse localAsset(String path) {
        if (!path.equals(BrowserPolicy.asset(BrowserPolicy.ORIGIN + "/app/" + path))) return blocked(404);
        try {
            String type = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css"
                : path.endsWith(".svg") ? "image/svg+xml" : path.endsWith(".woff2") ? "font/woff2"
                : path.endsWith(".html") ? "text/html" : "text/plain";
            return new WebResourceResponse(type, "UTF-8", 200, "OK", Collections.singletonMap("Cache-Control", "no-store"), getAssets().open("public/" + path));
        } catch (IOException error) { return blocked(404); }
    }

    private static WebResourceResponse blocked(int status) {
        return new WebResourceResponse("text/plain", "UTF-8", status, status == 403 ? "Forbidden" : "Not Found",
            Collections.singletonMap("Cache-Control", "no-store"), new ByteArrayInputStream(new byte[0]));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> object(Object value) {
        if (!(value instanceof Map)) throw new IllegalArgumentException("INVALID_REQUEST");
        return (Map<String, Object>) value;
    }

    private static Map<String, Object> errorReply(String id, String code, int status, boolean retryable) {
        Map<String, Object> problem = new LinkedHashMap<>(); problem.put("code", code); problem.put("retryable", retryable);
        if (status >= 400 && status <= 599) problem.put("status", status);
        Map<String, Object> output = new LinkedHashMap<>(); output.put("id", id); output.put("error", problem); return output;
    }

    private void eraseIdentity() {
        foreground = false; pageEpoch++; pending.clear();
        NativeTranslatorCore.Request cleanup = core.reset();
        workers.getQueue().clear(); transport.cancelActive(); transport.cleanup(cleanup);
    }

    private void failurePage(String reason) {
        eraseIdentity();
        destroyBrowser();
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); layout.setPadding(40, 100, 40, 40);
        TextView text = new TextView(this); text.setText(getString(R.string.safe_start_failure, reason, Build.VERSION.RELEASE)); text.setTextSize(18);
        layout.addView(text); setContentView(layout);
    }

    private void destroyBrowser() {
        WebView old = webView; webView = null;
        if (old != null) {
            if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                try { WebViewCompat.removeWebMessageListener(old, "YijingNative"); } catch (Exception ignored) {}
            }
            old.stopLoading(); old.setVisibility(android.view.View.GONE);
            if (old.getParent() instanceof android.view.ViewGroup) ((android.view.ViewGroup) old.getParent()).removeView(old);
            old.removeAllViews(); old.destroy();
        }
    }

    @Override protected void onStart() {
        super.onStart(); foreground = true;
        if (suspended && webView != null) { suspended = false; webView.loadUrl(BrowserPolicy.ENTRY); }
    }
    @Override protected void onStop() {
        eraseIdentity(); suspended = true;
        if (webView != null) { webView.stopLoading(); webView.loadUrl("about:blank"); }
        super.onStop();
    }
    @Override protected void onSaveInstanceState(Bundle output) { /* 不保存 WebView 或敏感内容。 */ }
    @Override protected void onDestroy() {
        eraseIdentity(); core.close(); destroyBrowser(); workers.shutdownNow(); transport.close(); super.onDestroy();
    }
}
