package io.github.misery522.yijing.host;

import io.github.misery522.yijing.core.BridgeFailure;
import io.github.misery522.yijing.core.NativeTranslatorCore;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.URI;
import java.security.cert.Certificate;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;

/** 保留真实 HttpsTransport，只替换系统连接边界，绝不发送测试请求。 */
final class HttpTests {
    private static final class Connection extends HttpsURLConnection {
        int status = 200;
        byte[] body = "{\"status\":\"ok\",\"api_version\":\"1\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String contentType = "application/json";
        SSLException failure;
        CountDownLatch reading;
        final CountDownLatch disconnected = new CountDownLatch(1);
        Connection() throws Exception { super(new URI("https://computer.private-tailnet.ts.net/api/v1/health").toURL()); }
        @Override public int getResponseCode() throws java.io.IOException {
            if (failure != null) throw failure;
            if (reading != null) {
                reading.countDown();
                try { if (!disconnected.await(2, TimeUnit.SECONDS)) throw new java.io.IOException(); }
                catch (InterruptedException error) { throw new java.io.IOException(); }
                throw new java.io.IOException();
            }
            return status;
        }
        @Override public String getContentType() { return contentType; }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(body); }
        @Override public void disconnect() { disconnected.countDown(); }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() {}
        @Override public String getCipherSuite() { return "SYSTEM_TLS_TEST_BOUNDARY"; }
        @Override public Certificate[] getLocalCertificates() { return null; }
        @Override public Certificate[] getServerCertificates() { return new Certificate[0]; }
    }
    private static Map<String, Object> command(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }
    private static void health(Connection connection, String error) throws Exception {
        try (HttpsTransport transport = new HttpsTransport(address -> connection)) {
            NativeTranslatorCore core = new NativeTranslatorCore(transport);
            core.invoke(command("command", "configure_backend", "origin", "https://computer.private-tailnet.ts.net"));
            try {
                core.invoke(command("command", "api_request", "generation", core.currentGeneration(), "request", command("operation", "health")));
                if (error != null) throw new AssertionError("HTTP_FAILURE_ACCEPTED");
            } catch (BridgeFailure failure) {
                if (!failure.code.equals(error)) throw new AssertionError("HTTP_ERROR_MAPPING_FAILED");
            }
            if (connection.getInstanceFollowRedirects() || connection.getUseCaches()
                || connection.getRequestProperty("Cookie") != null || connection.getRequestProperty("Authorization") != null
                || !"identity".equals(connection.getRequestProperty("Accept-Encoding"))
                || connection.getConnectTimeout() != 15000) throw new AssertionError("HTTP_POLICY_FAILED");
            if (!connection.disconnected.await(1, TimeUnit.SECONDS)) throw new AssertionError("HTTP_NOT_DISCONNECTED");
        }
    }
    static void run() {
        try {
            health(new Connection(), null);
            Connection redirect = new Connection(); redirect.status = 302; health(redirect, "REDIRECT_BLOCKED");
            Connection tls = new Connection(); tls.failure = new SSLException("private test exception must never be exposed"); health(tls, "TLS_REJECTED");
            Connection invalid = new Connection(); invalid.contentType = "text/html"; health(invalid, "INVALID_RESPONSE");
            Connection duplicate = new Connection(); duplicate.body = "{\"status\":\"ok\",\"status\":\"bad\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8); health(duplicate, "INVALID_RESPONSE");
            Connection large = new Connection(); large.body = new byte[NativeTranslatorCore.RESPONSE_LIMIT_BYTES + 1]; health(large, "INVALID_RESPONSE");
            Connection waiting = new Connection(); waiting.reading = new CountDownLatch(1);
            HttpsTransport transport = new HttpsTransport(address -> waiting);
            NativeTranslatorCore core = new NativeTranslatorCore(transport);
            core.invoke(command("command", "configure_backend", "origin", "https://computer.private-tailnet.ts.net"));
            Thread worker = new Thread(() -> {
                try { core.invoke(command("command", "api_request", "generation", core.currentGeneration(), "request", command("operation", "health"))); }
                catch (BridgeFailure expected) { /* 只在此测试等待已知断连。 */ }
            });
            worker.start();
            if (!waiting.reading.await(1, TimeUnit.SECONDS)) throw new AssertionError("HTTP_TEST_NOT_STARTED");
            transport.close();
            if (!waiting.disconnected.await(1, TimeUnit.SECONDS)) throw new AssertionError("CLOSE_DROPPED_DISCONNECT");
            worker.join(1000);
            if (worker.isAlive()) throw new AssertionError("HTTP_TEST_WORKER_LEAKED");
            System.out.println("HTTPS transport tests passed: 7");
        } catch (Exception failure) { throw new AssertionError("HTTP_TEST_FAILED", failure); }
    }
}
