package io.github.misery522.yijing.host;

import io.github.misery522.yijing.core.BridgeFailure;
import io.github.misery522.yijing.core.NativeTranslatorCore;
import io.github.misery522.yijing.core.NativeTranslatorCore.Request;
import io.github.misery522.yijing.core.NativeTranslatorCore.Response;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.CookieHandler;
import java.net.Proxy;
import java.net.URI;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;

/** 系统 TLS、精确源、无重定向；不读写 WebView Cookie，不输出网络数据。 */
public final class HttpsTransport implements NativeTranslatorCore.Transport, AutoCloseable {
    interface ConnectionFactory { HttpsURLConnection open(URL address) throws Exception; }
    private final ConnectionFactory connections;
    private final Set<HttpsURLConnection> active = Collections.synchronizedSet(new HashSet<>());
    private final ScheduledThreadPoolExecutor deadlines = new ScheduledThreadPoolExecutor(1);
    private final Set<HttpsURLConnection> disconnecting = new HashSet<>();
    private final ThreadPoolExecutor cancellations = new ThreadPoolExecutor(2, 2, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(16), new ThreadPoolExecutor.AbortPolicy());
    private final ThreadPoolExecutor cleanup = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(4), new ThreadPoolExecutor.AbortPolicy());

    public HttpsTransport() { this(address -> (HttpsURLConnection) address.openConnection(Proxy.NO_PROXY)); }
    HttpsTransport(ConnectionFactory connections) {
        this.connections = connections;
        deadlines.setRemoveOnCancelPolicy(true);
    }

    @Override
    public Response execute(Request request, int timeoutMillis) throws Exception {
        if (timeoutMillis < 1 || timeoutMillis > NativeTranslatorCore.NETWORK_TIMEOUT_MS)
            throw new BridgeFailure("INVALID_REQUEST", 0, false);
        // 独立宿主没有 Cookie 插件；若有额外代码装入全局处理器则失败关闭。
        if (CookieHandler.getDefault() != null) throw new BridgeFailure("FORBIDDEN", 0, false);
        URL address = new URI(request.origin + request.path).toURL();
        if (!"https".equals(address.getProtocol()) || address.getUserInfo() != null
            || address.getRef() != null || address.getQuery() != null || address.getPort() != -1
            || !request.path.startsWith("/api/v1/")) throw new BridgeFailure("INVALID_REQUEST", 0, false);
        HttpsURLConnection connection = connections.open(address);
        connection.setInstanceFollowRedirects(false);
        connection.setUseCaches(false);
        connection.setConnectTimeout(timeoutMillis);
        connection.setReadTimeout(timeoutMillis);
        connection.setRequestMethod(request.method);
        for (Map.Entry<String, String> header : request.headers.entrySet())
            connection.setRequestProperty(header.getKey(), header.getValue());
        active.add(connection);
        long expires = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        Thread caller = Thread.currentThread();
        Future<?> deadline = null;
        boolean[] finished = {false};
        try {
            deadline = deadlines.schedule(() -> {
                synchronized (finished) {
                    if (finished[0]) return;
                    caller.interrupt();
                }
                disconnectLater(connection);
            }, timeoutMillis, TimeUnit.MILLISECONDS);
            if (request.bodyMap != null) {
                byte[] body = StrictJson.stringify(request.bodyMap).getBytes(StandardCharsets.UTF_8);
                if (body.length > NativeTranslatorCore.REQUEST_LIMIT_BYTES) throw new BridgeFailure("REQUEST_TOO_LARGE", 0, false);
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
            }
            int status = connection.getResponseCode();
            remaining(expires);
            if (status >= 300 && status <= 399) throw new BridgeFailure("REDIRECT_BLOCKED", 0, false);
            // 错误正文不解析、不透传；Core 根据 HTTP 状态映射固定提示。
            if (status >= 400) return new Response(status, null);
            if (status == 204) return new Response(status, null);
            String contentType = connection.getContentType();
            if (contentType == null || !contentType.toLowerCase(java.util.Locale.ROOT).matches("application/json(?:\\s*;.*)?"))
                throw new BridgeFailure("INVALID_RESPONSE", 0, true);
            String encoding = connection.getContentEncoding();
            if (encoding != null && !"identity".equalsIgnoreCase(encoding)) throw new BridgeFailure("INVALID_RESPONSE", 0, true);
            int declared = connection.getContentLength();
            if (declared > NativeTranslatorCore.RESPONSE_LIMIT_BYTES) throw new BridgeFailure("INVALID_RESPONSE", 0, false);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[4096];
                while (true) {
                    connection.setReadTimeout(remaining(expires));
                    int count = input.read(buffer);
                    if (count < 0) break;
                    if (bytes.size() + count > NativeTranslatorCore.RESPONSE_LIMIT_BYTES) throw new BridgeFailure("INVALID_RESPONSE", 0, false);
                    bytes.write(buffer, 0, count);
                }
            }
            remaining(expires);
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
            Object decoded = StrictJson.parse(text);
            if (!(decoded instanceof Map)) throw new BridgeFailure("INVALID_RESPONSE", 0, false);
            @SuppressWarnings("unchecked") Map<String, Object> body = (Map<String, Object>) decoded;
            return new Response(status, body);
        } catch (SSLException error) { throw new BridgeFailure("TLS_REJECTED", 0, false); }
        catch (BridgeFailure error) { throw error; }
        catch (IllegalArgumentException | java.nio.charset.CharacterCodingException error) {
            throw new BridgeFailure("INVALID_RESPONSE", 0, true);
        } catch (Exception error) { throw new BridgeFailure("NETWORK_UNCONFIRMED", 0, true); }
        finally {
            synchronized (finished) {
                finished[0] = true;
                if (deadline != null) deadline.cancel(false);
                Thread.interrupted();
            }
            active.remove(connection);
            connection.disconnect();
        }
    }

    private static int remaining(long expires) throws BridgeFailure {
        long nanos = expires - System.nanoTime();
        if (nanos <= 0 || Thread.currentThread().isInterrupted()) throw new BridgeFailure("NETWORK_UNCONFIRMED", 0, true);
        return (int) Math.max(1, TimeUnit.NANOSECONDS.toMillis(nanos));
    }

    @Override
    public void cleanup(Request request) {
        if (request == null) return;
        try {
            cleanup.execute(() -> {
                try { execute(request, NativeTranslatorCore.CLEANUP_TIMEOUT_MS); }
                catch (Exception ignored) { /* 尽力一次；服务端 TTL 是最终兜底。 */ }
            });
        } catch (java.util.concurrent.RejectedExecutionException ignored) { /* 有界队列，不持久排队。 */ }
    }

    public void cancelActive() {
        synchronized (active) {
            for (HttpsURLConnection connection : active) disconnectLater(connection);
        }
    }

    private void disconnectLater(HttpsURLConnection connection) {
        synchronized (disconnecting) {
            if (!disconnecting.add(connection)) return;
            try {
                cancellations.execute(() -> {
                    try { connection.disconnect(); }
                    finally { synchronized (disconnecting) { disconnecting.remove(connection); } }
                });
            } catch (java.util.concurrent.RejectedExecutionException ignored) {
                disconnecting.remove(connection);
                // 仅可能在关闭后的迟到回调发生；执行请求的 finally 仍会断连。
            }
        }
    }

    @Override
    public void close() {
        cancelActive(); cleanup.shutdownNow(); deadlines.shutdownNow();
        // 不用 shutdownNow 丢弃刚提交的断连；不在 UI 线程等待网络释放。
        cancellations.shutdown();
    }
}
