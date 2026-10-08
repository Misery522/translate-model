package io.github.misery522.yijing.core;

import java.net.URI;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 普通 Java 安全核心：仅保存原生内存凭据与有界任务元数据。
 * HTTP、JSON 和生命周期调度由宿主实现；网络调用始终位于状态锁外。
 */
public final class NativeTranslatorCore {
    public static final int REQUEST_LIMIT_BYTES = 32768;
    public static final int RESPONSE_LIMIT_BYTES = 524288;
    public static final int NETWORK_TIMEOUT_MS = 15000;
    public static final int CLEANUP_TIMEOUT_MS = 5000;
    public static final int MAX_SESSIONS = 4;
    public static final int MAX_TRACKED_JOBS = 128;
    public static final long MAX_SAFE_INTEGER = 9007199254740991L;
    private static final Pattern UUID_PATTERN = Pattern.compile(
            "^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$");
    private static final Pattern TOKEN_PATTERN = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private static final Pattern PAIR_PATTERN = Pattern.compile("^[A-Za-z2-7]{12}$");
    private static final Pattern HOST_PATTERN = Pattern.compile(
            "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\."
            + "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.ts\\.net$");
    private static final Set<String> TERMINAL =
            names("succeeded", "failed", "cancelled", "timed_out");
    private static final Set<String> JOB_STATUSES =
            names("queued", "running", "succeeded", "failed", "cancelled", "timed_out");
    private static final Set<String> LANGUAGES =
            names("zh-Hans", "zh-Hant", "en", "ja", "ko", "fr", "de", "es",
                    "ru", "pt-BR", "ar", "it");
    private static final Set<String> STYLES = names("standard", "formal", "colloquial");
    private static final Set<String> DOMAINS =
            names("general", "technology", "business", "finance", "legal", "medical", "academic");
    private static final Set<String> MODES =
            names("auto", "translate", "annotate_code", "annotate_special");
    private static final Set<String> SECRET_KEYS =
            names("access_token", "refresh_token", "token", "token_type",
                    "authorization", "bearer_token");
    private static final Set<String> ERROR_CODES = names(
            "INVALID_REQUEST", "FORBIDDEN", "INVALID_RESPONSE", "STALE_OPERATION",
            "PAIRING_REQUIRED", "NETWORK_UNCONFIRMED", "REDIRECT_BLOCKED", "TLS_REJECTED",
            "ACCESS_DENIED", "NOT_FOUND", "CONFLICT", "RATE_LIMITED", "SERVICE_UNAVAILABLE",
            "REQUEST_TOO_LARGE", "REQUEST_REJECTED", "BACKEND_NOT_CONFIGURED");

    public interface Transport {
        Response execute(Request request, int timeoutMillis) throws Exception;

        /** 宿主必须覆盖为非阻塞、有界、单次最多 5 秒；失败由服务端 TTL 兜底。 */
        default void cleanup(Request request) {}
    }

    public static final class Request {
        public final String origin;
        public final String path;
        public final String method;
        public final Map<String, String> headers;
        public final Map<String, Object> bodyMap;

        private Request(String origin, String path, String method,
                Map<String, String> headers, Map<String, Object> bodyMap) {
            this.origin = origin;
            this.path = path;
            this.method = method;
            this.headers = Collections.unmodifiableMap(new LinkedHashMap<>(headers));
            this.bodyMap = bodyMap;
        }
    }

    public static final class Response {
        public final int status;
        public final Map<String, Object> bodyMap;

        public Response(int status, Map<String, Object> bodyMap) {
            this.status = status;
            this.bodyMap = bodyMap;
        }
    }

    private static final class Session {
        final String id;
        boolean closing;
        boolean uncertain;
        boolean used;
        Session(String id) { this.id = id; }
    }

    private static final class JobRecord {
        final String id;
        final Session session;
        final String clientRequestId;
        final long workGeneration;
        boolean terminal;
        JobRecord(String id, Session session, String clientRequestId, long workGeneration) {
            this.id = id;
            this.session = session;
            this.clientRequestId = clientRequestId;
            this.workGeneration = workGeneration;
        }
    }

    private static final class Ticket {
        final long generation;
        final String origin;
        final String operation;
        final String bearer;
        Session session;
        JobRecord job;
        Ticket(long generation, String origin, String operation, String bearer) {
            this.generation = generation;
            this.origin = origin;
            this.operation = operation;
            this.bearer = bearer;
        }
    }

    private final Object lock = new Object();
    private final Transport transport;
    private final Map<String, Session> sessions = new LinkedHashMap<>();
    private final Map<String, JobRecord> jobs = new LinkedHashMap<>();
    private final Set<Ticket> pendingSessions = new LinkedHashSet<>();
    private final Set<Ticket> pendingSubmissions = new LinkedHashSet<>();
    private long generation;
    private String origin;
    private String bearer;
    private String deviceId;
    private boolean closed;

    public NativeTranslatorCore(Transport transport) {
        if (transport == null) throw new IllegalArgumentException("TRANSPORT_REQUIRED");
        this.transport = transport;
    }

    public long currentGeneration() {
        synchronized (lock) { return generation; }
    }

    /** 只供状态检查；真正桥接交付须用 deliverIfCurrent，避免检查与发送之间失效。 */
    public boolean canDeliver(Map<String, Object> response) {
        synchronized (lock) {
            try {
                return !closed && response != null
                        && integer(response.get("generation"), true) == generation;
            } catch (BridgeFailure ignored) {
                return false;
            }
        }
    }

    /** UI 线程只允许在此回调中执行短消息投递；不得编码正文或等待网络。 */
    public boolean deliverIfCurrent(Map<String, Object> response, Runnable delivery) {
        if (delivery == null) throw new IllegalArgumentException("DELIVERY_REQUIRED");
        synchronized (lock) {
            if (!canDeliver(response)) return false;
            // 同一状态锁覆盖检查和短交付，401 / 配对 / 后台撤销不能插入两者之间。
            delivery.run();
            return true;
        }
    }

    /** 后台立即撤销本地身份；只返回冻结的清理计划，不等待网络。 */
    public Request reset() {
        synchronized (lock) {
            Request cleanup = cleanupSnapshot();
            invalidate();
            return cleanup;
        }
    }

    public Request close() {
        synchronized (lock) {
            if (closed) return null;
            Request cleanup = cleanupSnapshot();
            invalidate();
            closed = true;
            origin = null;
            return cleanup;
        }
    }

    public Map<String, Object> invoke(Map<String, Object> input) {
        Map<String, Object> command = copyMap(input, false);
        String name = text(command.get("command"), 64, false);
        if ("backend_status".equals(name)) {
            exact(command, false, "command");
            synchronized (lock) { requireOpen(); return statusView(); }
        }
        if ("configure_backend".equals(name)) {
            exact(command, false, "command", "origin");
            String nextOrigin = normalizeOrigin(text(command.get("origin"), 1024, false));
            Request cleanup;
            Map<String, Object> result;
            synchronized (lock) {
                requireOpen();
                cleanup = cleanupSnapshot();
                invalidate();
                origin = nextOrigin;
                result = statusView();
            }
            dispatchCleanup(cleanup);
            return result;
        }
        if (!"api_request".equals(name)) throw invalid(false);
        exact(command, false, "command", "generation", "request");
        long expectedGeneration = integer(command.get("generation"), false);
        Map<String, Object> operation = validateOperation(command.get("request"));
        String operationName = (String) operation.get("operation");
        if ("pair".equals(operationName)) return pair(expectedGeneration, operation);
        if ("logout".equals(operationName)) return logout(expectedGeneration);
        return api(expectedGeneration, operation);
    }

    private Map<String, Object> pair(long expected, Map<String, Object> operation) {
        Ticket ticket;
        Request cleanup;
        synchronized (lock) {
            requireConnection(expected);
            cleanup = cleanupSnapshot();
            invalidate();
            ticket = new Ticket(generation, origin, "pair", null);
        }
        dispatchCleanup(cleanup);
        Request request = request(ticket.origin, "/api/v1/pair/exchange", "POST", null,
                data("code", operation.get("code"), "device_name", operation.get("device_name"),
                        "auth_mode", "bearer"));
        Response response = exchange(ticket, request);
        Map<String, Object> raw = response.bodyMap;
        Map<String, Object> publicAuth;
        String token;
        try {
            requireStatus(response, 201);
            raw = copyMap(raw, true);
            exact(raw, true, "device_id", "device_name", "auth_mode", "expires_at",
                    "csrf_token", "access_token", "token_type");
            token = text(raw.get("access_token"), 128, true);
            if (!TOKEN_PATTERN.matcher(token).matches() || !"Bearer".equals(raw.get("token_type")))
                throw invalid(true);
            publicAuth = authView(data("device_id", raw.get("device_id"),
                    "device_name", raw.get("device_name"), "auth_mode", raw.get("auth_mode"),
                    "expires_at", raw.get("expires_at"), "csrf_token", raw.get("csrf_token")));
            assertNoCredentialReflection(publicAuth, token);
        } catch (BridgeFailure failure) {
            synchronized (lock) { requireTicket(ticket); }
            throw failure;
        }
        synchronized (lock) {
            if (!isCurrent(ticket)) {
                // 已生成的迟到凭据仅用于旧源清理，绝不重新保存身份。
                cleanup = request(ticket.origin, "/api/v1/auth/session", "DELETE", token, null);
            } else {
                bearer = token;
                deviceId = (String) publicAuth.get("device_id");
                return envelope(201, publicAuth, ticket.generation);
            }
        }
        dispatchCleanup(cleanup);
        throw stale();
    }

    private Map<String, Object> logout(long expected) {
        Ticket ticket;
        Request request;
        synchronized (lock) {
            requireConnection(expected);
            requirePaired();
            request = cleanupSnapshot();
            invalidate();
            ticket = new Ticket(generation, origin, "logout", null);
        }
        try {
            Response response = exchange(ticket, request);
            synchronized (lock) {
                requireTicket(ticket);
                requireStatus(response, 204);
                if (response.bodyMap != null) throw invalid(true);
                return envelope(204, null, ticket.generation);
            }
        } catch (BridgeFailure failure) {
            dispatchCleanup(request);
            throw failure;
        }
    }

    private Map<String, Object> api(long expected, Map<String, Object> operation) {
        Ticket ticket;
        Request request;
        List<Request> emptySessionCleanups = new ArrayList<>();
        synchronized (lock) {
            requireConnection(expected);
            String name = (String) operation.get("operation");
            if (!"health".equals(name)) requirePaired();
            ticket = new Ticket(generation, origin, name, bearer);
            if ("create_session".equals(name)) {
                while (sessions.size() + pendingSessions.size() >= MAX_SESSIONS) {
                    Session empty = null;
                    for (Session candidate : sessions.values()) {
                        if (!candidate.used && !candidate.closing && !candidate.uncertain) {
                            empty = candidate;
                            break;
                        }
                    }
                    if (empty == null) throw failure("REQUEST_REJECTED", 409, false);
                    emptySessionCleanups.add(request(ticket.origin,
                            "/api/v1/sessions/" + empty.id, "DELETE", ticket.bearer, null));
                    retireSession(empty);
                }
                pendingSessions.add(ticket);
            } else if ("translate".equals(name) || "delete_session".equals(name)) {
                ticket.session = knownSession((String) operation.get("session_id"));
                if ("translate".equals(name)) {
                    if (ticket.session.closing || ticket.session.uncertain)
                        throw failure("CONFLICT", 409, false);
                    reserveSubmission(ticket);
                    ticket.session.used = true;
                } else {
                    // 本地先失效；删除失败时仍允许用户再次删除，不恢复旧结果。
                    ticket.session.closing = true;
                    forgetSessionJobs(ticket.session);
                }
            } else if ("job".equals(name) || "cancel".equals(name)) {
                ticket.job = jobs.get(uuid(operation.get("job_id"), false));
                if (ticket.job == null || ticket.job.session.closing) throw invalid(false);
                ticket.session = ticket.job.session;
            }
            request = operationRequest(ticket, operation);
        }
        for (Request cleanup : emptySessionCleanups) dispatchCleanup(cleanup);
        try {
            Response response = exchange(ticket, request);
            synchronized (lock) {
                requireTicket(ticket);
                if (response.status != expectedStatus(ticket.operation)) {
                    handleRejection(ticket, response.status);
                    throw httpFailure(response.status);
                }
                return complete(ticket, operation, response);
            }
        } catch (BridgeFailure failure) {
            synchronized (lock) {
                if (isCurrent(ticket) && failure.status == 401) invalidate();
                if (isCurrent(ticket) && "translate".equals(ticket.operation)
                        && sessions.get(ticket.session.id) == ticket.session
                        && (failure.status == 0 || failure.status >= 500)) {
                    ticket.session.uncertain = true;
                }
            }
            throw failure;
        } finally {
            synchronized (lock) {
                pendingSessions.remove(ticket);
                pendingSubmissions.remove(ticket);
            }
        }
    }

    private Map<String, Object> complete(Ticket ticket, Map<String, Object> operation,
            Response response) {
        String name = ticket.operation;
        if ("delete_session".equals(name)) {
            if (response.bodyMap != null) throw invalid(true);
            retireSession(ticket.session);
            return envelope(204, null, ticket.generation);
        }
        Map<String, Object> body = copyMap(response.bodyMap, true);
        assertPublic(body, 0);
        assertNoCredentialReflection(body, ticket.bearer);
        if ("health".equals(name)) {
            exact(body, true, "status", "api_version");
            if (!"ok".equals(body.get("status")) || !"1".equals(body.get("api_version")))
                throw invalid(true);
        } else if ("auth".equals(name)) {
            body = authView(body);
            if (!deviceId.equals(body.get("device_id"))) throw invalid(true);
        } else if ("create_session".equals(name)) {
            if (!pendingSessions.contains(ticket)) throw stale();
            exact(body, true, "session_id", "generation", "expires_at");
            String id = uuid(body.get("session_id"), true);
            long workGeneration = integer(body.get("generation"), true);
            timestamp(body.get("expires_at"));
            if (sessions.containsKey(id)) throw invalid(true);
            Session session = new Session(id);
            session.used = workGeneration > 0;
            pendingSessions.remove(ticket);
            sessions.put(id, session);
        } else {
            body = jobView(body);
            String jobId = uuid(body.get("job_id"), true);
            String sessionId = uuid(body.get("session_id"), true);
            String requestId = uuid(body.get("client_request_id"), true);
            long workGeneration = integer(body.get("generation"), true);
            if (sessions.get(ticket.session.id) != ticket.session || ticket.session.closing) throw stale();
            if (!ticket.session.id.equals(sessionId)) throw invalid(true);
            JobRecord tracked;
            if ("translate".equals(name)) {
                if (!pendingSubmissions.contains(ticket)) throw stale();
                if (!uuid(operation.get("client_request_id"), false).equals(requestId)) throw invalid(true);
                pendingSubmissions.remove(ticket);
                tracked = jobs.get(jobId);
                if (tracked == null) {
                    tracked = new JobRecord(jobId, ticket.session, requestId, workGeneration);
                    jobs.put(jobId, tracked);
                }
            } else {
                tracked = ticket.job;
                if (jobs.get(tracked.id) != tracked) throw stale();
            }
            if (!tracked.id.equals(jobId) || tracked.session != ticket.session
                    || !tracked.clientRequestId.equals(requestId)
                    || tracked.workGeneration != workGeneration) throw invalid(true);
            boolean terminal = TERMINAL.contains((String) body.get("status"));
            if (tracked.terminal && !terminal) throw stale();
            if (!tracked.terminal && terminal) {
                tracked.terminal = true;
                jobs.remove(jobId);
                jobs.put(jobId, tracked);
            }
        }
        return envelope(response.status, body, ticket.generation);
    }

    private Response exchange(Ticket ticket, Request request) {
        try {
            Response response = transport.execute(request, NETWORK_TIMEOUT_MS);
            if (response == null) throw invalid(true);
            return response;
        } catch (Exception error) {
            synchronized (lock) { requireTicket(ticket); }
            if (error instanceof BridgeFailure) {
                BridgeFailure failure = (BridgeFailure) error;
                if (ERROR_CODES.contains(failure.code)
                        && (failure.status == 0 || (failure.status >= 400 && failure.status <= 599)))
                    throw new BridgeFailure(failure.code, failure.status, failure.retryable);
            }
            throw failure("NETWORK_UNCONFIRMED", 0, true);
        }
    }

    private void handleRejection(Ticket ticket, int status) {
        if (status == 401) {
            invalidate();
        } else if (status == 404 && ticket.session != null) {
            if ("delete_session".equals(ticket.operation) || "translate".equals(ticket.operation))
                retireSession(ticket.session);
            else if (ticket.job != null && jobs.get(ticket.job.id) == ticket.job)
                jobs.remove(ticket.job.id);
        }
    }

    private void reserveSubmission(Ticket ticket) {
        while (jobs.size() + pendingSubmissions.size() >= MAX_TRACKED_JOBS) {
            String oldest = null;
            for (JobRecord job : jobs.values()) {
                if (job.terminal) { oldest = job.id; break; }
            }
            if (oldest == null) throw failure("REQUEST_REJECTED", 409, false);
            jobs.remove(oldest);
        }
        pendingSubmissions.add(ticket);
    }

    private void forgetSessionJobs(Session session) {
        List<String> remove = new ArrayList<>();
        for (JobRecord job : jobs.values()) if (job.session == session) remove.add(job.id);
        for (String id : remove) jobs.remove(id);
        List<Ticket> pending = new ArrayList<>();
        for (Ticket ticket : pendingSubmissions) if (ticket.session == session) pending.add(ticket);
        pendingSubmissions.removeAll(pending);
    }

    private void retireSession(Session session) {
        if (sessions.get(session.id) == session) sessions.remove(session.id);
        forgetSessionJobs(session);
    }

    private Session knownSession(String id) {
        Session session = sessions.get(uuid(id, false));
        if (session == null) throw invalid(false);
        return session;
    }

    private void requireOpen() {
        if (closed) throw failure("FORBIDDEN", 403, false);
    }
    private void requireConnection(long expected) {
        requireOpen();
        if (expected != generation) throw stale();
        if (origin == null) throw failure("BACKEND_NOT_CONFIGURED", 0, false);
    }
    private void requirePaired() {
        if (bearer == null) throw failure("PAIRING_REQUIRED", 401, false);
    }
    private boolean isCurrent(Ticket ticket) {
        return !closed && ticket.generation == generation && ticket.origin.equals(origin);
    }
    private void requireTicket(Ticket ticket) {
        if (!isCurrent(ticket)) throw stale();
    }
    private void invalidate() {
        bearer = null;
        deviceId = null;
        sessions.clear();
        jobs.clear();
        pendingSessions.clear();
        pendingSubmissions.clear();
        if (generation == MAX_SAFE_INTEGER) {
            closed = true;
            throw failure("CONFLICT", 409, false);
        }
        generation++;
    }

    private Map<String, Object> statusView() {
        return data("origin", origin, "paired", bearer != null, "generation", generation);
    }
    private Request cleanupSnapshot() {
        return origin == null || bearer == null ? null
                : request(origin, "/api/v1/auth/session", "DELETE", bearer, null);
    }
    private void dispatchCleanup(Request request) {
        if (request == null) return;
        try { transport.cleanup(request); } catch (Exception ignored) {
            // 清理失败不恢复本地凭据；宿主不得输出原异常。
        }
    }

    private static Request operationRequest(Ticket ticket, Map<String, Object> operation) {
        String name = ticket.operation;
        if ("health".equals(name))
            return request(ticket.origin, "/api/v1/health", "GET", null, null);
        if ("auth".equals(name))
            return request(ticket.origin, "/api/v1/auth/session", "GET", ticket.bearer, null);
        if ("create_session".equals(name))
            return request(ticket.origin, "/api/v1/sessions", "POST", ticket.bearer, data());
        if ("delete_session".equals(name))
            return request(ticket.origin, "/api/v1/sessions/" + ticket.session.id,
                    "DELETE", ticket.bearer, null);
        if ("translate".equals(name))
            return request(ticket.origin, "/api/v1/translations", "POST", ticket.bearer,
                    data("session_id", ticket.session.id, "client_request_id",
                            uuid(operation.get("client_request_id"), false),
                            "request", operation.get("request")));
        String path = "/api/v1/translations/" + ticket.job.id;
        return request(ticket.origin, "cancel".equals(name) ? path + "/cancel" : path,
                "cancel".equals(name) ? "POST" : "GET", ticket.bearer,
                "cancel".equals(name) ? data() : null);
    }

    private static Request request(String origin, String path, String method, String token,
            Map<String, Object> body) {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Accept", "application/json");
        headers.put("Accept-Encoding", "identity");
        headers.put("Cache-Control", "no-store");
        if (body != null) headers.put("Content-Type", "application/json");
        if (token != null) headers.put("Authorization", "Bearer " + token);
        return new Request(origin, path, method, headers, body);
    }
    private static int expectedStatus(String operation) {
        if ("create_session".equals(operation)) return 201;
        if ("delete_session".equals(operation)) return 204;
        if ("translate".equals(operation)) return 202;
        return 200;
    }
    private static void requireStatus(Response response, int expected) {
        if (response.status != expected) throw httpFailure(response.status);
    }
    private static BridgeFailure httpFailure(int status) {
        if (status >= 300 && status < 400) return failure("REDIRECT_BLOCKED", 0, false);
        if (status == 401) return failure("ACCESS_DENIED", 401, false);
        if (status == 403) return failure("ACCESS_DENIED", 403, false);
        if (status == 404) return failure("NOT_FOUND", 404, false);
        if (status == 409) return failure("CONFLICT", 409, false);
        if (status == 413) return failure("REQUEST_TOO_LARGE", 413, false);
        if (status == 429) return failure("RATE_LIMITED", 429, true);
        if (status >= 500 && status <= 599) return failure("SERVICE_UNAVAILABLE", status, true);
        if (status >= 400 && status <= 499) return failure("REQUEST_REJECTED", status, false);
        return invalid(true);
    }
    private static BridgeFailure failure(String code, int status, boolean retryable) {
        return new BridgeFailure(code, status, retryable);
    }
    private static BridgeFailure invalid(boolean response) {
        return failure(response ? "INVALID_RESPONSE" : "INVALID_REQUEST", response ? 0 : 400, false);
    }
    private static BridgeFailure stale() { return failure("STALE_OPERATION", 0, false); }
    private static Map<String, Object> envelope(int status, Map<String, Object> body, long generation) {
        return data("status", status, "body", body, "generation", generation);
    }

    private static Map<String, Object> validateOperation(Object raw) {
        Map<String, Object> value = copyMap(raw, false);
        String name = text(value.get("operation"), 64, false);
        if (names("health", "auth", "logout", "create_session").contains(name)) {
            exact(value, false, "operation");
        } else if ("pair".equals(name)) {
            exact(value, false, "operation", "code", "device_name");
            if (!PAIR_PATTERN.matcher(text(value.get("code"), 12, false)).matches())
                throw invalid(false);
            String device = text(value.get("device_name"), 64, false);
            if (blank(device)) throw invalid(false);
        } else if ("delete_session".equals(name)) {
            exact(value, false, "operation", "session_id");
            uuid(value.get("session_id"), false);
        } else if ("job".equals(name) || "cancel".equals(name)) {
            exact(value, false, "operation", "job_id");
            uuid(value.get("job_id"), false);
        } else if ("translate".equals(name)) {
            exact(value, false, "operation", "session_id", "client_request_id", "request");
            uuid(value.get("session_id"), false);
            uuid(value.get("client_request_id"), false);
            Map<String, Object> request = copyMap(value.get("request"), false);
            exact(request, false, "text", "source_language", "target_language",
                    "style", "domain", "task_mode");
            String source = text(request.get("source_language"), 64, false);
            String target = text(request.get("target_language"), 64, false);
            String input = text(request.get("text"), 4000, false);
            if (blank(input) || input.indexOf('\0') >= 0
                    || (!"auto".equals(source) && !LANGUAGES.contains(source))
                    || !LANGUAGES.contains(target) || !STYLES.contains(request.get("style"))
                    || !DOMAINS.contains(request.get("domain")) || !MODES.contains(request.get("task_mode")))
                throw invalid(false);
        } else throw invalid(false);
        return value;
    }

    private static String normalizeOrigin(String input) {
        if (!input.startsWith("https://") || input.length() > 1024
                || input.matches(".*[\\s\\x00-\\x1f\\x7f\\\\%@?#].*")) throw invalid(false);
        try {
            URI uri = new URI(input);
            String host = uri.getHost();
            if (!"https".equals(uri.getScheme()) || host == null || uri.getRawUserInfo() != null
                    || uri.getRawQuery() != null || uri.getRawFragment() != null
                    || (uri.getPort() != -1 && uri.getPort() != 443)
                    || (uri.getRawPath() != null && !"".equals(uri.getRawPath())
                            && !"/".equals(uri.getRawPath()))
                    || !HOST_PATTERN.matcher(host.toLowerCase(Locale.ROOT)).matches())
                throw invalid(false);
            return "https://" + host.toLowerCase(Locale.ROOT);
        } catch (BridgeFailure failure) { throw failure; }
        catch (Exception ignored) { throw invalid(false); }
    }

    private static Map<String, Object> authView(Map<String, Object> body) {
        exact(body, true, "device_id", "device_name", "auth_mode", "expires_at", "csrf_token");
        assertPublic(body, 0);
        uuid(body.get("device_id"), true);
        text(body.get("device_name"), 64, true);
        timestamp(body.get("expires_at"));
        if (!"bearer".equals(body.get("auth_mode")) || body.get("csrf_token") != null)
            throw invalid(true);
        return body;
    }

    private static Map<String, Object> jobView(Map<String, Object> body) {
        exact(body, true, "job_id", "session_id", "client_request_id", "generation", "status",
                "created_at", "expires_at", "result", "error");
        uuid(body.get("job_id"), true);
        uuid(body.get("session_id"), true);
        uuid(body.get("client_request_id"), true);
        integer(body.get("generation"), true);
        if (!JOB_STATUSES.contains(body.get("status"))) throw invalid(true);
        timestamp(body.get("created_at"));
        timestamp(body.get("expires_at"));
        if (body.get("result") != null) resultView(copyMap(body.get("result"), true));
        else if ("succeeded".equals(body.get("status"))) throw invalid(true);
        if (body.get("error") != null) {
            Map<String, Object> error = copyMap(body.get("error"), true);
            exact(error, true, "code", "message", "retryable", "request_id");
            text(error.get("code"), 128, true);
            text(error.get("message"), 4096, true);
            if (!(error.get("retryable") instanceof Boolean)) throw invalid(true);
            uuid(error.get("request_id"), true);
        }
        return body;
    }

    private static void resultView(Map<String, Object> result) {
        exact(result, true, "route", "detected_language", "detection_status", "preserved_source",
                "translated_text", "annotated_copy", "annotations", "applied_terms",
                "warnings", "elapsed_ms");
        if (!names("translate_text", "annotate_code", "annotate_special", "mixed_document")
                .contains(result.get("route"))
                || !names("detected", "uncertain", "mixed").contains(result.get("detection_status")))
            throw invalid(true);
        text(result.get("detected_language"), 64, true);
        string(result.get("preserved_source"), RESPONSE_LIMIT_BYTES, true);
        nullableText(result.get("translated_text"));
        nullableText(result.get("annotated_copy"));
        integer(result.get("elapsed_ms"), true);
        for (Object warning : list(result.get("warnings"))) string(warning, 4096, true);
        for (Object raw : list(result.get("annotations"))) {
            Map<String, Object> annotation = copyMap(raw, true);
            exact(annotation, true, "kind", "source_fragment", "explanation", "location", "risk");
            text(annotation.get("kind"), 128, true);
            string(annotation.get("source_fragment"), RESPONSE_LIMIT_BYTES, true);
            string(annotation.get("explanation"), RESPONSE_LIMIT_BYTES, true);
            nullableText(annotation.get("location"));
            nullableText(annotation.get("risk"));
        }
        for (Object raw : list(result.get("applied_terms"))) {
            Map<String, Object> term = copyMap(raw, true);
            exact(term, true, "source", "target", "count");
            string(term.get("source"), 4096, true);
            string(term.get("target"), 4096, true);
            if (integer(term.get("count"), true) < 1) throw invalid(true);
        }
    }

    private static void nullableText(Object value) {
        if (value != null) string(value, RESPONSE_LIMIT_BYTES, true);
    }
    private static List<?> list(Object value) {
        if (!(value instanceof List)) throw invalid(true);
        return (List<?>) value;
    }
    private static void timestamp(Object value) {
        String timestamp = text(value, 128, true);
        try { OffsetDateTime.parse(timestamp, DateTimeFormatter.ISO_OFFSET_DATE_TIME); }
        catch (Exception ignored) { throw invalid(true); }
    }
    private static String uuid(Object value, boolean response) {
        String id = text(value, 36, response);
        if (!UUID_PATTERN.matcher(id).matches()) throw invalid(response);
        return id.toLowerCase(Locale.ROOT);
    }
    private static String text(Object value, int max, boolean response) {
        String text = string(value, max, response);
        if (text.length() == 0) throw invalid(response);
        return text;
    }
    private static String string(Object value, int max, boolean response) {
        if (!(value instanceof String)) throw invalid(response);
        String text = (String) value;
        if (text.codePointCount(0, text.length()) > max) throw invalid(response);
        for (int i = 0; i < text.length(); i++) {
            char part = text.charAt(i);
            if (Character.isHighSurrogate(part)) {
                if (++i >= text.length() || !Character.isLowSurrogate(text.charAt(i))) throw invalid(response);
            } else if (Character.isLowSurrogate(part)) throw invalid(response);
        }
        return text;
    }
    private static boolean blank(String value) {
        for (int offset = 0; offset < value.length();) {
            int point = value.codePointAt(offset);
            if (!Character.isWhitespace(point) && !Character.isSpaceChar(point) && point != 0xfeff)
                return false;
            offset += Character.charCount(point);
        }
        return true;
    }
    private static long integer(Object value, boolean response) {
        if (!(value instanceof Number)) throw invalid(response);
        double number = ((Number) value).doubleValue();
        if (Double.isNaN(number) || Double.isInfinite(number) || number < 0
                || number > MAX_SAFE_INTEGER || number != Math.floor(number)) throw invalid(response);
        return (long) number;
    }
    private static void exact(Map<String, Object> value, boolean response, String... keys) {
        if (value.size() != keys.length || !value.keySet().containsAll(Arrays.asList(keys)))
            throw invalid(response);
    }
    private static Set<String> names(String... names) {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(names)));
    }
    private static Map<String, Object> data(Object... fields) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < fields.length; i += 2) result.put((String) fields[i], fields[i + 1]);
        return Collections.unmodifiableMap(result);
    }
    @SuppressWarnings("unchecked")
    private static Map<String, Object> copyMap(Object value, boolean response) {
        if (!(value instanceof Map)) throw invalid(response);
        return (Map<String, Object>) copyData(value, response, 0, new int[] {0});
    }
    private static Object copyData(Object value, boolean response, int depth, int[] count) {
        if (++count[0] > 20000 || depth > 16) throw invalid(response);
        if (value instanceof Map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> item : ((Map<?, ?>) value).entrySet()) {
                if (!(item.getKey() instanceof String)) throw invalid(response);
                String key = string(item.getKey(), 128, response);
                result.put(key, copyData(item.getValue(), response, depth + 1, count));
            }
            return Collections.unmodifiableMap(result);
        }
        if (value instanceof List) {
            List<Object> result = new ArrayList<>();
            for (Object item : (List<?>) value) result.add(copyData(item, response, depth + 1, count));
            return Collections.unmodifiableList(result);
        }
        if (value == null || value instanceof Boolean) return value;
        if (value instanceof String) return string(value, RESPONSE_LIMIT_BYTES, response);
        if (value instanceof Number) {
            double number = ((Number) value).doubleValue();
            if (Double.isInfinite(number) || Double.isNaN(number)) throw invalid(response);
            if (!(value instanceof Integer) && !(value instanceof Long) && !(value instanceof Double)
                    && !(value instanceof Float) && !(value instanceof Short) && !(value instanceof Byte))
                throw invalid(response);
            return value;
        }
        throw invalid(response);
    }
    private static void assertPublic(Object value, int depth) {
        if (depth > 16) throw invalid(true);
        if (value instanceof Map) {
            for (Map.Entry<?, ?> item : ((Map<?, ?>) value).entrySet()) {
                if (SECRET_KEYS.contains(((String) item.getKey()).toLowerCase(Locale.ROOT)))
                    throw invalid(true);
                assertPublic(item.getValue(), depth + 1);
            }
        } else if (value instanceof List) {
            for (Object item : (List<?>) value) assertPublic(item, depth + 1);
        }
    }
    private static void assertNoCredentialReflection(Object value, String credential) {
        if (credential == null) return;
        if (value instanceof String) {
            if (((String) value).contains(credential)) throw invalid(true);
        } else if (value instanceof Map) {
            for (Object child : ((Map<?, ?>) value).values())
                assertNoCredentialReflection(child, credential);
        } else if (value instanceof List) {
            for (Object child : (List<?>) value) assertNoCredentialReflection(child, credential);
        }
    }
}
