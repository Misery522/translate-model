package io.github.misery522.yijing.core;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 无 Android / JSON / JUnit 依赖的真实 Java 单测入口。
 * 传输全部模拟；随机测试凭据不写日志，不访问网络或模型。
 */
public final class NativeTranslatorCoreTest {
    private static final String ORIGIN = "https://computer.private-tailnet.ts.net";
    private static final String OTHER = "https://second.private-tailnet.ts.net";
    private static final String DATE = "2099-01-01T00:00:00Z";
    private static final String DEVICE = uuid(9000);
    private static int cases;

    @FunctionalInterface
    private interface Test { void run() throws Exception; }
    @FunctionalInterface
    private interface Handler {
        NativeTranslatorCore.Response respond(NativeTranslatorCore.Request request) throws Exception;
    }

    private static final class FakeTransport implements NativeTranslatorCore.Transport {
        final List<NativeTranslatorCore.Request> requests = new CopyOnWriteArrayList<>();
        final List<NativeTranslatorCore.Request> cleanups = new CopyOnWriteArrayList<>();
        final Map<String, Map<String, Object>> jobs = new LinkedHashMap<>();
        final AtomicInteger nextSession = new AtomicInteger();
        final AtomicInteger nextJob = new AtomicInteger();
        volatile Handler handler;
        volatile boolean immediateTerminal;
        volatile String token = randomToken();
        volatile String lastSession;

        @Override
        public NativeTranslatorCore.Response execute(NativeTranslatorCore.Request request,
                int timeoutMillis) throws Exception {
            require(timeoutMillis == NativeTranslatorCore.NETWORK_TIMEOUT_MS, "network deadline");
            requests.add(request);
            Handler current = handler;
            return current == null ? defaultResponse(request) : current.respond(request);
        }
        @Override
        public void cleanup(NativeTranslatorCore.Request request) { cleanups.add(request); }

        synchronized NativeTranslatorCore.Response defaultResponse(NativeTranslatorCore.Request request) {
            String path = request.path;
            if (path.equals("/api/v1/pair/exchange")) {
                token = randomToken();
                return response(201, pairBody(token));
            }
            if (path.equals("/api/v1/health"))
                return response(200, map("status", "ok", "api_version", "1"));
            if (path.equals("/api/v1/auth/session"))
                return request.method.equals("DELETE") ? response(204, null) : response(200, authBody());
            if (path.equals("/api/v1/sessions")) {
                lastSession = uuid(nextSession.incrementAndGet());
                return response(201, map("session_id", lastSession, "generation", 0, "expires_at", DATE));
            }
            if (path.startsWith("/api/v1/sessions/")) return response(204, null);
            if (path.equals("/api/v1/translations")) {
                int index = nextJob.incrementAndGet();
                Map<String, Object> job = jobBody(uuid(10000 + index),
                        (String) request.bodyMap.get("session_id"),
                        (String) request.bodyMap.get("client_request_id"),
                        index, immediateTerminal ? "succeeded" : "running");
                jobs.put((String) job.get("job_id"), job);
                return response(202, job);
            }
            String id = path.substring("/api/v1/translations/".length());
            boolean cancel = id.endsWith("/cancel");
            if (cancel) id = id.substring(0, id.length() - "/cancel".length());
            Map<String, Object> job = jobs.get(id);
            if (job == null) return response(404, map());
            if (cancel) {
                job = jobBody(id, (String) job.get("session_id"), (String) job.get("client_request_id"),
                        ((Number) job.get("generation")).longValue(), "cancelled");
                jobs.put(id, job);
            }
            return response(200, job);
        }
    }

    private static final class Fixture {
        final FakeTransport transport = new FakeTransport();
        final NativeTranslatorCore core = new NativeTranslatorCore(transport);
        Fixture() {
            core.invoke(map("command", "configure_backend", "origin", ORIGIN));
            invoke(core, map("operation", "pair", "code", "ABCDEFGHIJKL", "device_name", "测试手机"));
        }
        String session() {
            return (String) body(invoke(core, map("operation", "create_session"))).get("session_id");
        }
        Map<String, Object> submit(String session, int index) {
            return body(invoke(core, submission(session, index)));
        }
    }

    public static void main(String[] args) throws Exception {
        ScheduledExecutorService watchdog = Executors.newSingleThreadScheduledExecutor((runnable) -> {
            Thread thread = new Thread(runnable, "native-core-test-deadline");
            thread.setDaemon(true);
            return thread;
        });
        watchdog.schedule(() -> {
            System.err.println("Native core tests exceeded 60 seconds.");
            System.exit(124);
        }, 60, TimeUnit.SECONDS);
        try {
            run("protocol routing", NativeTranslatorCoreTest::routing);
            run("configuration invalidates", NativeTranslatorCoreTest::configurationInvalidates);
            run("reset clears credentials", NativeTranslatorCoreTest::resetClears);
            run("logout local first", NativeTranslatorCoreTest::logoutLocalFirst);
            run("late pair cleanup", NativeTranslatorCoreTest::latePair);
            run("late ordinary response", NativeTranslatorCoreTest::lateResponse);
            run("late deleted submission", NativeTranslatorCoreTest::lateDeletedSubmission);
            run("terminal regression", NativeTranslatorCoreTest::terminalRegression);
            run("terminal eviction", NativeTranslatorCoreTest::terminalEviction);
            run("terminal confirmation order", NativeTranslatorCoreTest::terminalOrder);
            run("concurrent late terminal", NativeTranslatorCoreTest::lateTerminal);
            run("evicted late terminal", NativeTranslatorCoreTest::evictedLateTerminal);
            run("active bound", NativeTranslatorCoreTest::activeBound);
            run("pending capacity", NativeTranslatorCoreTest::pendingCapacity);
            run("session bound", NativeTranslatorCoreTest::sessionBound);
            run("empty session refresh", NativeTranslatorCoreTest::emptySessionRefresh);
            run("late created session", NativeTranslatorCoreTest::lateCreatedSession);
            run("failed deletion does not restore", NativeTranslatorCoreTest::failedDeletion);
            run("uncertain submission", NativeTranslatorCoreTest::uncertainSubmission);
            run("credential mutation isolation", NativeTranslatorCoreTest::mutationIsolation);
            run("structured secrets", NativeTranslatorCoreTest::secretsRejected);
            run("credential reflection", NativeTranslatorCoreTest::credentialReflection);
            run("pair credential reflection", NativeTranslatorCoreTest::pairCredentialReflection);
            run("native error sanitization", NativeTranslatorCoreTest::errorSanitization);
            run("close and delivery", NativeTranslatorCoreTest::closeAndDelivery);
            run("atomic delivery blocks invalidation", NativeTranslatorCoreTest::atomicDelivery);
            run("stale atomic delivery skipped", NativeTranslatorCoreTest::staleDelivery);
            run("http rejection", NativeTranslatorCoreTest::httpRejection);
            run("response identity", NativeTranslatorCoreTest::responseIdentity);
            run("untrusted transport 401", NativeTranslatorCoreTest::transport401);
            run("extra request keys", NativeTranslatorCoreTest::extraRequestKeys);
            run("pair code boundary", NativeTranslatorCoreTest::pairCodeBoundary);
            run("nested data limit", NativeTranslatorCoreTest::nestedDataLimit);
            run("unicode input count", NativeTranslatorCoreTest::unicodeCount);
            for (String origin : new String[] {
                    "http://computer.private-tailnet.ts.net", "https://public.example.com",
                    "https://127.0.0.1", ORIGIN + ":8766", ORIGIN + "/api", ORIGIN + "?a=b",
                    ORIGIN + "#fragment", "https://user:pass@computer.private-tailnet.ts.net",
                    "https://computer%2eprivate-tailnet.ts.net", ORIGIN + ".",
                    ORIGIN + "\\other", " " + ORIGIN, ORIGIN + "\n"}) {
                run("invalid origin", () -> {
                    NativeTranslatorCore core = new NativeTranslatorCore(new FakeTransport());
                    expect("INVALID_REQUEST",
                            () -> core.invoke(map("command", "configure_backend", "origin", origin)));
                });
            }
            for (String name : new String[] {"shell", "fetch", "download", "execute", "open_url"}) {
                run("unknown operation", () -> {
                    Fixture fixture = new Fixture();
                    expect("INVALID_REQUEST", () -> invoke(fixture.core, map("operation", name)));
                });
            }
            for (Object generation : new Object[] {-1, 0.5, Double.NaN, Double.POSITIVE_INFINITY,
                    NativeTranslatorCore.MAX_SAFE_INTEGER + 1, "1"}) {
                run("unsafe generation", () -> {
                    Fixture fixture = new Fixture();
                    expect("INVALID_REQUEST", () -> fixture.core.invoke(
                            map("command", "api_request", "generation", generation,
                                    "request", map("operation", "health"))));
                });
            }
            System.out.println("Native core tests: " + cases + " passed.");
        } catch (Throwable failure) {
            // 断言和网络假对象也不得把测试凭据、正文或原异常写日志。
            System.err.println("Native core tests failed after " + cases + " completed cases.");
            System.exit(1);
        } finally {
            watchdog.shutdownNow();
        }
    }

    private static void routing() {
        Fixture f = new Fixture();
        String session = f.session();
        String token = f.transport.token;
        Map<String, Object> auth = body(invoke(f.core, map("operation", "auth")));
        require(auth.size() == 5 && !auth.containsKey("access_token"), "auth projection");
        invoke(f.core, map("operation", "health"));
        Map<String, Object> job = f.submit(session, 1);
        String id = (String) job.get("job_id");
        invoke(f.core, map("operation", "job", "job_id", id));
        invoke(f.core, map("operation", "cancel", "job_id", id));
        invoke(f.core, map("operation", "delete_session", "session_id", session));
        Map<String, Object> logout = invoke(f.core, map("operation", "logout"));
        require(logout.get("body") == null, "204 null body");
        boolean createSeen = false, cancelSeen = false, translateSeen = false;
        for (NativeTranslatorCore.Request request : f.transport.requests) {
            require(!request.headers.containsKey("Cookie") && !request.headers.containsKey("Origin")
                    && !request.headers.containsKey("Referer")
                    && !request.headers.containsKey("X-CSRF-Token"), "native header whitelist");
            require("identity".equals(request.headers.get("Accept-Encoding")), "no implicit gzip");
            if (request.path.equals("/api/v1/pair/exchange")) {
                require(!request.headers.containsKey("Authorization")
                        && "bearer".equals(request.bodyMap.get("auth_mode")), "pair native mode");
            } else if (request.path.equals("/api/v1/health")) {
                require(!request.headers.containsKey("Authorization"), "health public");
            } else {
                require(("Bearer " + token).equals(request.headers.get("Authorization")),
                        "core owned bearer");
            }
            if (request.path.equals("/api/v1/sessions")) {
                createSeen = true;
                require(request.method.equals("POST") && request.bodyMap.isEmpty(), "session body");
            }
            if (request.path.endsWith("/cancel")) {
                cancelSeen = true;
                require(request.method.equals("POST") && request.bodyMap.isEmpty(), "cancel body");
            }
            if (request.path.equals("/api/v1/translations")) {
                translateSeen = true;
                require(request.method.equals("POST") && request.bodyMap.size() == 3, "submit body");
            }
            if (request.method.equals("DELETE")) require(request.bodyMap == null, "delete no body");
        }
        require(createSeen && cancelSeen && translateSeen, "fixed routes covered");
    }

    private static void configurationInvalidates() {
        Fixture f = new Fixture();
        String token = f.transport.token;
        long old = f.core.currentGeneration();
        Map<String, Object> status = f.core.invoke(map("command", "configure_backend", "origin", OTHER + ":443/"));
        require(OTHER.equals(status.get("origin")) && Boolean.FALSE.equals(status.get("paired")),
                "canonical origin");
        require(f.core.currentGeneration() > old && f.transport.cleanups.size() == 1, "new generation");
        NativeTranslatorCore.Request cleanup = f.transport.cleanups.get(0);
        require(cleanup.origin.equals(ORIGIN)
                && cleanup.headers.get("Authorization").equals("Bearer " + token), "old origin snapshot");
        expect("PAIRING_REQUIRED", () -> invoke(f.core, map("operation", "auth")));
    }

    private static void resetClears() {
        Fixture f = new Fixture();
        String session = f.session();
        f.submit(session, 1);
        long old = f.core.currentGeneration();
        NativeTranslatorCore.Request cleanup = f.core.reset();
        require(cleanup != null && cleanup.origin.equals(ORIGIN), "reset cleanup");
        require(f.core.currentGeneration() > old
                && Boolean.FALSE.equals(f.core.invoke(map("command", "backend_status")).get("paired")),
                "reset unpaired");
        expect("PAIRING_REQUIRED", () -> invoke(f.core, map("operation", "create_session")));
    }

    private static void logoutLocalFirst() throws Exception {
        Fixture f = new Fixture();
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release logout");
            return response(503, map("error", "do-not-forward"));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("SERVICE_UNAVAILABLE",
                    () -> invoke(f.core, map("operation", "logout"))));
            require(entered.await(2, TimeUnit.SECONDS), "logout entered");
            require(Boolean.FALSE.equals(f.core.invoke(map("command", "backend_status")).get("paired")),
                    "logout cleared before network");
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void latePair() throws Exception {
        FakeTransport transport = new FakeTransport();
        NativeTranslatorCore core = new NativeTranslatorCore(transport);
        core.invoke(map("command", "configure_backend", "origin", ORIGIN));
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        String lateToken = randomToken();
        transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release pair");
            return response(201, pairBody(lateToken));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION", () -> invoke(core,
                    map("operation", "pair", "code", "ABCDEFGHIJKL", "device_name", "测试手机"))));
            require(entered.await(2, TimeUnit.SECONDS), "pair entered");
            core.reset();
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
            require(Boolean.FALSE.equals(core.invoke(map("command", "backend_status")).get("paired")),
                    "late pair cannot restore");
            require(transport.cleanups.size() == 1
                    && transport.cleanups.get(0).headers.get("Authorization")
                            .equals("Bearer " + lateToken), "late token cleanup");
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void lateResponse() throws Exception {
        Fixture f = new Fixture();
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release auth");
            return response(200, authBody());
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION",
                    () -> invoke(f.core, map("operation", "auth"))));
            require(entered.await(2, TimeUnit.SECONDS), "auth entered");
            f.core.reset();
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void lateDeletedSubmission() throws Exception {
        Fixture f = new Fixture();
        String session = f.session();
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            if (!request.path.equals("/api/v1/translations")) return f.transport.defaultResponse(request);
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release submission");
            return response(202, jobBody(uuid(11000), session, uuid(1), 1, "running"));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION",
                    () -> invoke(f.core, submission(session, 1))));
            require(entered.await(2, TimeUnit.SECONDS), "submission entered");
            invoke(f.core, map("operation", "delete_session", "session_id", session));
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
            expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "job", "job_id", uuid(11000))));
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void terminalRegression() {
        Fixture f = new Fixture();
        String session = f.session();
        String id = (String) f.submit(session, 1).get("job_id");
        invoke(f.core, map("operation", "cancel", "job_id", id));
        f.transport.jobs.put(id, jobBody(id, session, uuid(1), 1, "running"));
        expect("STALE_OPERATION", () -> invoke(f.core, map("operation", "job", "job_id", id)));
    }

    private static void terminalEviction() {
        Fixture f = new Fixture();
        f.transport.immediateTerminal = true;
        String session = f.session();
        String first = null, last = null;
        for (int i = 1; i <= 129; i++) {
            String id = (String) f.submit(session, i).get("job_id");
            if (i == 1) first = id;
            last = id;
        }
        String old = first;
        expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "job", "job_id", old)));
        require(body(invoke(f.core, map("operation", "job", "job_id", last)))
                .get("status").equals("succeeded"), "new job remains");
    }

    private static void activeBound() {
        Fixture f = new Fixture();
        String session = f.session();
        for (int i = 1; i <= 128; i++) f.submit(session, i);
        int requests = f.transport.requests.size();
        expect("REQUEST_REJECTED", () -> f.submit(session, 129));
        require(requests == f.transport.requests.size(), "bound rejects before network");
        require(body(invoke(f.core, map("operation", "job", "job_id", uuid(10001))))
                .get("status").equals("running"), "active not evicted");
    }

    private static void pendingCapacity() throws Exception {
        Fixture f = new Fixture();
        String session = f.session();
        for (int i = 1; i <= 127; i++) f.submit(session, i);
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release pending");
            return f.transport.defaultResponse(request);
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> pending = executor.submit(() -> f.submit(session, 128));
            require(entered.await(2, TimeUnit.SECONDS), "pending entered");
            expect("REQUEST_REJECTED", () -> f.submit(session, 129));
            finish.countDown();
            pending.get(3, TimeUnit.SECONDS);
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void sessionBound() {
        Fixture f = new Fixture();
        List<String> ids = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            String id = f.session();
            ids.add(id);
            f.submit(id, i + 1);
        }
        expect("REQUEST_REJECTED", f::session);
        invoke(f.core, map("operation", "delete_session", "session_id", ids.get(0)));
        require(f.session() != null, "delete releases slot");
    }

    private static void emptySessionRefresh() {
        Fixture f = new Fixture();
        String first = f.session();
        for (int i = 0; i < 9; i++) f.session();
        require(f.transport.cleanups.size() == 6, "bounded empty refresh");
        NativeTranslatorCore.Request cleanup = f.transport.cleanups.get(0);
        require(cleanup.path.equals("/api/v1/sessions/" + first)
                && cleanup.origin.equals(ORIGIN) && cleanup.method.equals("DELETE"), "empty cleanup");
        expect("INVALID_REQUEST", () -> invoke(f.core,
                map("operation", "delete_session", "session_id", first)));
    }

    private static void terminalOrder() {
        Fixture f = new Fixture();
        String session = f.session();
        for (int i = 1; i <= 128; i++) f.submit(session, i);
        String first = uuid(10001), second = uuid(10002);
        f.transport.jobs.put(second, jobBody(second, session, uuid(2), 2, "succeeded"));
        invoke(f.core, map("operation", "job", "job_id", second));
        f.transport.jobs.put(first, jobBody(first, session, uuid(1), 1, "succeeded"));
        invoke(f.core, map("operation", "job", "job_id", first));
        f.submit(session, 129);
        expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "job", "job_id", second)));
        require("succeeded".equals(body(invoke(f.core,
                map("operation", "job", "job_id", first))).get("status")), "first confirmed order");
    }

    private static void lateTerminal() throws Exception {
        Fixture f = new Fixture();
        String session = f.session();
        String id = (String) f.submit(session, 1).get("job_id");
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            if (!request.path.equals("/api/v1/translations/" + id)) return f.transport.defaultResponse(request);
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release old running");
            return response(200, jobBody(id, session, uuid(1), 1, "running"));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION",
                    () -> invoke(f.core, map("operation", "job", "job_id", id))));
            require(entered.await(2, TimeUnit.SECONDS), "old running entered");
            invoke(f.core, map("operation", "cancel", "job_id", id));
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void evictedLateTerminal() throws Exception {
        Fixture f = new Fixture();
        String session = f.session();
        for (int i = 1; i <= 128; i++) f.submit(session, i);
        String id = uuid(10001);
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        AtomicInteger reads = new AtomicInteger();
        f.transport.handler = (request) -> {
            if (!request.path.equals("/api/v1/translations/" + id)) return f.transport.defaultResponse(request);
            if (reads.incrementAndGet() == 1) {
                entered.countDown();
                require(finish.await(3, TimeUnit.SECONDS), "release evicted terminal");
            }
            return response(200, jobBody(id, session, uuid(1), 1, "succeeded"));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION",
                    () -> invoke(f.core, map("operation", "job", "job_id", id))));
            require(entered.await(2, TimeUnit.SECONDS), "old terminal entered");
            invoke(f.core, map("operation", "job", "job_id", id));
            f.submit(session, 129);
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
            expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "job", "job_id", id)));
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void lateCreatedSession() throws Exception {
        Fixture f = new Fixture();
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release old session");
            return response(201, map("session_id", uuid(88), "generation", 0, "expires_at", DATE));
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> old = executor.submit(() -> expect("STALE_OPERATION", f::session));
            require(entered.await(2, TimeUnit.SECONDS), "old session entered");
            f.core.reset();
            finish.countDown();
            old.get(3, TimeUnit.SECONDS);
            expect("PAIRING_REQUIRED", () -> invoke(f.core, map("operation", "create_session")));
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void failedDeletion() {
        Fixture f = new Fixture();
        String session = f.session();
        String id = (String) f.submit(session, 1).get("job_id");
        f.transport.handler = (request) -> response(503, map("error", randomToken()));
        expect("SERVICE_UNAVAILABLE", () -> invoke(f.core,
                map("operation", "delete_session", "session_id", session)));
        f.transport.handler = null;
        expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "job", "job_id", id)));
        expect("CONFLICT", () -> f.submit(session, 2));
        invoke(f.core, map("operation", "delete_session", "session_id", session));
        require(f.session() != null, "deletion retry releases state");
    }

    private static void uncertainSubmission() {
        Fixture f = new Fixture();
        String session = f.session();
        f.transport.handler = (request) -> { throw new Exception(randomToken()); };
        expect("NETWORK_UNCONFIRMED", () -> f.submit(session, 1));
        f.transport.handler = null;
        int before = f.transport.requests.size();
        expect("CONFLICT", () -> f.submit(session, 2));
        require(before == f.transport.requests.size(), "unconfirmed cannot resend");
        invoke(f.core, map("operation", "delete_session", "session_id", session));
        String fresh = f.session();
        require(f.submit(fresh, 3) != null, "new session resumes");
    }

    private static void mutationIsolation() throws Exception {
        Fixture f = new Fixture();
        String session = f.session();
        Map<String, Object> content = translation();
        Map<String, Object> operation = map("operation", "translate", "session_id", session,
                "client_request_id", uuid(1), "request", content);
        CountDownLatch entered = new CountDownLatch(1), finish = new CountDownLatch(1);
        f.transport.handler = (request) -> {
            entered.countDown();
            require(finish.await(3, TimeUnit.SECONDS), "release mutation");
            require("Hello".equals(((Map<?, ?>) request.bodyMap.get("request")).get("text")), "frozen text");
            return f.transport.defaultResponse(request);
        };
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<?> pending = executor.submit(() -> invoke(f.core, operation));
            require(entered.await(2, TimeUnit.SECONDS), "mutation entered");
            content.put("text", randomToken());
            finish.countDown();
            pending.get(3, TimeUnit.SECONDS);
        } finally { finish.countDown(); executor.shutdownNow(); }
    }

    private static void secretsRejected() {
        Fixture f = new Fixture();
        f.transport.handler = (request) -> {
            Map<String, Object> auth = authBody();
            auth.put("access_token", randomToken());
            return response(200, auth);
        };
        expect("INVALID_RESPONSE", () -> invoke(f.core, map("operation", "auth")));
    }

    private static void credentialReflection() {
        Fixture f = new Fixture();
        f.transport.handler = (request) -> {
            Map<String, Object> auth = authBody();
            auth.put("device_name", f.transport.token);
            return response(200, auth);
        };
        expect("INVALID_RESPONSE", () -> invoke(f.core, map("operation", "auth")));
    }

    private static void pairCredentialReflection() {
        FakeTransport transport = new FakeTransport();
        NativeTranslatorCore core = new NativeTranslatorCore(transport);
        core.invoke(map("command", "configure_backend", "origin", ORIGIN));
        String token = randomToken();
        transport.handler = (request) -> {
            Map<String, Object> pair = pairBody(token);
            pair.put("device_name", token);
            return response(201, pair);
        };
        expect("INVALID_RESPONSE", () -> invoke(core,
                map("operation", "pair", "code", "ABCDEFGHIJKL", "device_name", "测试手机")));
        require(Boolean.FALSE.equals(core.invoke(map("command", "backend_status")).get("paired")),
                "reflected pair not saved");
    }

    private static void errorSanitization() {
        Fixture f = new Fixture();
        String marker = randomToken();
        f.transport.handler = (request) -> { throw new Exception(marker); };
        try {
            invoke(f.core, map("operation", "auth"));
            throw new AssertionError("expected sanitized failure");
        } catch (BridgeFailure failure) {
            require("NETWORK_UNCONFIRMED".equals(failure.code)
                    && !failure.getMessage().contains(marker) && failure.getCause() == null
                    && failure.getStackTrace().length == 0, "no sensitive diagnostic");
        }
    }

    private static void closeAndDelivery() {
        Fixture f = new Fixture();
        Map<String, Object> before = f.core.invoke(map("command", "backend_status"));
        require(f.core.canDeliver(before), "deliver current");
        require(f.core.close() != null && !f.core.canDeliver(before), "close drops delivery");
        expect("FORBIDDEN", () -> f.core.invoke(map("command", "backend_status")));
        require(f.core.close() == null, "idempotent close");
    }

    private static void atomicDelivery() throws Exception {
        Fixture f = new Fixture();
        Map<String, Object> current = f.core.invoke(map("command", "backend_status"));
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        CountDownLatch resetStarted = new CountDownLatch(1), resetDone = new CountDownLatch(1);
        AtomicInteger delivered = new AtomicInteger();
        ExecutorService sender = Executors.newSingleThreadExecutor();
        Thread resetter = new Thread(() -> {
            resetStarted.countDown();
            f.core.reset();
            resetDone.countDown();
        }, "native-core-test-invalidation");
        Future<Boolean> completion = sender.submit(() -> f.core.deliverIfCurrent(current, () -> {
            entered.countDown();
            try { require(release.await(2, TimeUnit.SECONDS), "delivery release bound"); }
            catch (InterruptedException error) { throw new AssertionError("delivery interrupted"); }
            require(f.core.canDeliver(current), "generation held through delivery");
            delivered.incrementAndGet();
        }));
        try {
            require(entered.await(1, TimeUnit.SECONDS), "delivery started");
            resetter.start();
            require(resetStarted.await(1, TimeUnit.SECONDS), "invalidation started");
            long until = System.nanoTime() + TimeUnit.SECONDS.toNanos(1);
            while (resetter.getState() != Thread.State.BLOCKED
                    && resetDone.getCount() != 0 && System.nanoTime() < until) Thread.yield();
            // 确认撤销已经争抢状态锁，而不是仅靠调度延迟推断“未执行”。
            require(resetter.getState() == Thread.State.BLOCKED && resetDone.getCount() == 1,
                    "invalidation cannot split check and delivery");
            release.countDown();
            require(completion.get(1, TimeUnit.SECONDS), "current delivered atomically");
            require(resetDone.await(1, TimeUnit.SECONDS), "invalidation proceeds afterwards");
            require(delivered.get() == 1 && !f.core.canDeliver(current), "ordered delivery then reset");
        } finally {
            release.countDown();
            sender.shutdownNow();
            resetter.join(1000);
        }
    }

    private static void staleDelivery() {
        Fixture f = new Fixture();
        Map<String, Object> old = f.core.invoke(map("command", "backend_status"));
        AtomicInteger delivered = new AtomicInteger();
        f.core.reset();
        require(!f.core.deliverIfCurrent(old, delivered::incrementAndGet), "stale delivery refused");
        require(!f.core.deliverIfCurrent(null, delivered::incrementAndGet), "missing response refused");
        Map<String, Object> current = f.core.invoke(map("command", "backend_status"));
        require(f.core.deliverIfCurrent(current, delivered::incrementAndGet), "new status can deliver");
        f.core.close();
        require(!f.core.deliverIfCurrent(current, delivered::incrementAndGet), "closed delivery refused");
        require(delivered.get() == 1, "refused deliveries never call callback");
    }

    private static void httpRejection() {
        Fixture f = new Fixture();
        f.transport.handler = (request) -> response(302, map("Location", OTHER));
        expect("REDIRECT_BLOCKED", () -> invoke(f.core, map("operation", "auth")));
        f.transport.handler = (request) -> response(401, map("error", randomToken()));
        expect("ACCESS_DENIED", () -> invoke(f.core, map("operation", "auth")));
        require(Boolean.FALSE.equals(f.core.invoke(map("command", "backend_status")).get("paired")),
                "401 clears bearer");
    }

    private static void responseIdentity() {
        Fixture f = new Fixture();
        f.transport.handler = (request) -> response(201,
                map("session_id", "1-1-1-1-1", "generation", 0, "expires_at", DATE));
        expect("INVALID_RESPONSE", f::session);
        f.transport.handler = null;
        String session = f.session();
        f.transport.handler = (request) -> response(202, jobBody(uuid(11001), uuid(888), uuid(1), 1, "running"));
        expect("INVALID_RESPONSE", () -> f.submit(session, 1));
    }

    private static void transport401() {
        Fixture f = new Fixture();
        f.transport.handler = (request) -> { throw new BridgeFailure("ACCESS_DENIED", 401, false); };
        expect("ACCESS_DENIED", () -> invoke(f.core, map("operation", "auth")));
        require(Boolean.FALSE.equals(f.core.invoke(map("command", "backend_status")).get("paired")),
                "transport 401 clears credential");
    }

    private static void extraRequestKeys() {
        Fixture f = new Fixture();
        expect("INVALID_REQUEST", () -> invoke(f.core,
                map("operation", "health", "url", OTHER)));
        expect("INVALID_REQUEST", () -> invoke(f.core,
                map("operation", "auth", "headers", map("Authorization", randomToken()))));
    }

    private static void pairCodeBoundary() {
        Fixture f = new Fixture();
        for (String code : new String[] {"ABCDEFGHIJK1", "ABCDEFGHIJK8", "short", "ABCDEFGHIJKLM"}) {
            expect("INVALID_REQUEST", () -> invoke(f.core,
                    map("operation", "pair", "code", code, "device_name", "测试手机")));
        }
        StringBuilder name = new StringBuilder();
        for (int i = 0; i < 65; i++) name.appendCodePoint(0x1f642);
        expect("INVALID_REQUEST", () -> invoke(f.core,
                map("operation", "pair", "code", "ABCDEFGHIJKL", "device_name", name.toString())));
    }

    private static void nestedDataLimit() {
        Fixture f = new Fixture();
        Map<String, Object> deep = map();
        Map<String, Object> top = deep;
        for (int i = 0; i < 20; i++) {
            Map<String, Object> child = map();
            deep.put("child", child);
            deep = child;
        }
        Map<String, Object> payload = top;
        expect("INVALID_REQUEST", () -> f.core.invoke(payload));
    }

    private static void unicodeCount() {
        Fixture f = new Fixture();
        String session = f.session();
        Map<String, Object> content = translation();
        StringBuilder exact = new StringBuilder();
        for (int i = 0; i < 4000; i++) exact.appendCodePoint(0x1f642);
        content.put("text", exact.toString());
        invoke(f.core, map("operation", "translate", "session_id", session,
                "client_request_id", uuid(1), "request", content));
        exact.appendCodePoint(0x1f642);
        content.put("text", exact.toString());
        expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "translate",
                "session_id", session, "client_request_id", uuid(2), "request", content)));
        content.put("text", "before\0after");
        expect("INVALID_REQUEST", () -> invoke(f.core, map("operation", "translate",
                "session_id", session, "client_request_id", uuid(3), "request", content)));
    }

    private static Map<String, Object> invoke(NativeTranslatorCore core, Map<String, Object> operation) {
        return core.invoke(map("command", "api_request", "generation", core.currentGeneration(),
                "request", operation));
    }
    @SuppressWarnings("unchecked")
    private static Map<String, Object> body(Map<String, Object> envelope) {
        return (Map<String, Object>) envelope.get("body");
    }
    private static Map<String, Object> submission(String session, int index) {
        return map("operation", "translate", "session_id", session,
                "client_request_id", uuid(index), "request", translation());
    }
    private static Map<String, Object> translation() {
        return map("text", "Hello", "source_language", "auto", "target_language", "zh-Hans",
                "style", "standard", "domain", "general", "task_mode", "auto");
    }
    private static Map<String, Object> authBody() {
        return map("device_id", DEVICE, "device_name", "测试手机", "auth_mode", "bearer",
                "csrf_token", null, "expires_at", DATE);
    }
    private static Map<String, Object> pairBody(String token) {
        Map<String, Object> body = authBody();
        body.put("access_token", token);
        body.put("token_type", "Bearer");
        return body;
    }
    private static Map<String, Object> jobBody(String id, String session, String client,
            long generation, String status) {
        return map("job_id", id, "session_id", session, "client_request_id", client,
                "generation", generation, "status", status, "created_at", DATE,
                "expires_at", DATE, "result", "succeeded".equals(status)
                        ? map("route", "translate_text", "detected_language", "en",
                                "detection_status", "detected", "preserved_source", "Hello",
                                "translated_text", "你好", "annotated_copy", null,
                                "annotations", new ArrayList<>(), "applied_terms", new ArrayList<>(),
                                "warnings", new ArrayList<>(), "elapsed_ms", 1) : null,
                "error", null);
    }
    private static NativeTranslatorCore.Response response(int status, Map<String, Object> body) {
        return new NativeTranslatorCore.Response(status, body);
    }
    private static Map<String, Object> map(Object... fields) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < fields.length; i += 2) result.put((String) fields[i], fields[i + 1]);
        return result;
    }
    private static String uuid(int value) {
        return String.format("aaaaaaaa-aaaa-4aaa-8aaa-%012x", value);
    }
    private static String randomToken() {
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
    private static void expect(String code, Runnable operation) {
        try { operation.run(); }
        catch (BridgeFailure failure) {
            require(code.equals(failure.code), "controlled error code");
            return;
        }
        throw new AssertionError("expected controlled failure");
    }
    private static void require(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
    }
    private static void run(String name, Test test) throws Exception {
        try { test.run(); }
        catch (Throwable failure) {
            // 标签是固定常量，绝不打印 failure 内容。
            System.err.println("Failed case: " + name);
            throw failure;
        }
        cases++;
    }
}
