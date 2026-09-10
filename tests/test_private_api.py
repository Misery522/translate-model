"""私人 API 的配对、跨设备隔离、取消与容量保护。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from yijing.glossary import GlossaryDocument
from yijing_api.app import create_app
from yijing_api.auth import AuthStore
from yijing_api.config import ApiSettings

ORIGIN = "http://127.0.0.1:8765"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeRunner:
    def __init__(self, delay=0, fail=False):
        self.delay, self.fail = delay, fail
        self.active = self.max_active = self.calls = 0
        self.closed = False
        self.cancelled = 0

    async def run(self, request):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("private-original-content must not leak")
            return {
                "route": "translate_text",
                "detected_language": "en",
                "detection_status": "detected",
                "preserved_source": request["text"],
                "translated_text": "你好",
            }
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def close(self):
        self.closed = True


class FakeService:
    def __init__(self):
        self.document = GlossaryDocument()

    def list_glossary(self):
        return self.document.model_copy(deep=True)

    def save_glossary(self, document):
        self.document = document.model_copy(deep=True)
        return self.document


def make_client(*, settings=None, runner=None, clock=time.monotonic):
    settings = settings or ApiSettings()
    app = create_app(settings, runner=runner or FakeRunner(), service=FakeService(), clock=clock)
    return app, TestClient(app, base_url=settings.public_origin)


def pair(client, app, *, mode="cookie", fresh=False):
    code = app.state.auth.issue_pair_code() if fresh else app.state.pairing_code
    response = client.post(
        "/api/v1/pair/exchange",
        json={
            "code": code,
            "device_name": "测试设备",
            "auth_mode": mode,
        },
        headers={"Origin": app.state.settings.public_origin},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    headers = {"Origin": app.state.settings.public_origin}
    if mode == "cookie":
        headers["X-CSRF-Token"] = result["csrf_token"]
    else:
        headers["Authorization"] = "Bearer " + result["access_token"]
    return result, headers


def session(client, headers):
    response = client.post("/api/v1/sessions", json={}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def submit(client, headers, session_id, *, text="Hello", request_id=None):
    return client.post(
        "/api/v1/translations",
        headers=headers,
        json={
            "session_id": session_id,
            "client_request_id": request_id or str(uuid4()),
            "request": {"text": text, "target_language": "zh-Hans"},
        },
    )


def wait_status(client, headers, job_id, expected, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/translations/{job_id}", headers=headers)
        if response.status_code == 200 and response.json()["status"] in expected:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Task did not reach {expected}: {response.text}")


def test_pair_cookie_and_success_preserve_contract_and_hide_credential():
    app, client = make_client()
    with client:
        result, headers = pair(client, app)
        assert result["access_token"] is None
        assert app.state.pairing_code is None
        assert app.state.settings.cookie_name in client.cookies
        auth = client.get("/api/v1/auth/session").json()
        assert auth["device_id"] == result["device_id"]
        request_id = str(uuid4())
        work = session(client, headers)
        response = submit(client, headers, work, request_id=request_id)
        assert response.status_code == 202
        done = wait_status(client, headers, response.json()["job_id"], {"succeeded"})
        assert done["client_request_id"] == request_id
        assert done["generation"] == 1
        assert done["result"]["translated_text"] == "你好"
        assert app.state.jobs.jobs[done["job_id"]].request is None
        assert "no-store" in client.get("/api/v1/auth/session").headers["cache-control"]


def test_https_cookie_has_secure_host_prefix_and_no_domain():
    app, client = make_client(settings=ApiSettings(public_origin="https://translator.example.com"))
    with client:
        response = client.post(
            "/api/v1/pair/exchange",
            headers={"Origin": app.state.settings.public_origin},
            json={
                "code": app.state.pairing_code,
                "device_name": "Phone",
                "auth_mode": "cookie",
            },
        )
        cookie = response.headers["set-cookie"]
        assert "__Host-yijing_session=" in cookie
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Domain=" not in cookie


def test_pair_code_single_use_expiry_and_rate_limit():
    clock = Clock()
    store = AuthStore(ApiSettings(), clock)
    code = store.issue_pair_code()
    store.exchange(code, "one", "bearer", "peer")
    with pytest.raises(Exception, match="INVALID_PAIR_CODE"):
        store.exchange(code, "two", "bearer", "peer")
    code = store.issue_pair_code()
    clock.now += 301
    with pytest.raises(Exception, match="INVALID_PAIR_CODE"):
        store.exchange(code, "two", "bearer", "peer")
    for _ in range(4):
        with pytest.raises(Exception, match="INVALID_PAIR_CODE"):
            store.exchange("A" * 12, "two", "bearer", "peer")
    with pytest.raises(Exception, match="PAIR_RATE_LIMIT"):
        store.exchange("A" * 12, "two", "bearer", "peer")


@pytest.mark.parametrize(
    "origin", ["https://attacker.example", "null", "http://127.0.0.1:8765.attacker.example"]
)
def test_bad_origin_rejected_before_handler(origin):
    app, client = make_client()
    with client:
        response = client.post(
            "/api/v1/pair/exchange",
            headers={"Origin": origin},
            json={
                "code": app.state.pairing_code,
                "device_name": "bad",
                "auth_mode": "cookie",
            },
        )
        assert response.status_code == 403
        assert not app.state.auth.active_device_ids()


def test_host_forwarding_and_pair_generation_are_not_authorization():
    app, client = make_client()
    with client:
        assert client.get("/api/v1/health", headers={"Host": "attacker.example"}).status_code == 400
        response = client.post(
            "/api/v1/sessions",
            json={},
            headers={
                "Origin": ORIGIN,
                "X-Forwarded-For": "127.0.0.1",
                "X-Forwarded-Proto": "https",
            },
        )
        assert response.status_code == 401
        assert client.post("/api/v1/pair/new", json={}).status_code == 404


def test_cookie_writes_need_csrf_and_origin_or_matching_referer():
    app, client = make_client()
    with client:
        auth, headers = pair(client, app)
        assert (
            client.post("/api/v1/sessions", json={}, headers={"Origin": ORIGIN}).status_code == 403
        )
        assert (
            client.post(
                "/api/v1/sessions", json={}, headers={"X-CSRF-Token": auth["csrf_token"]}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/sessions", json={}, headers={**headers, "X-CSRF-Token": "bad"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/sessions",
                json={},
                headers={
                    "Referer": ORIGIN + "/app",
                    "X-CSRF-Token": auth["csrf_token"],
                },
            ).status_code
            == 201
        )


def test_native_bearer_and_cookie_bearer_ambiguity():
    app, client = make_client(settings=ApiSettings(client_origins=("tauri://localhost",)))
    with client:
        auth, _headers = pair(client, app, mode="bearer")
        headers = {"Authorization": "Bearer " + auth["access_token"]}
        assert client.post("/api/v1/sessions", json={}, headers=headers).status_code == 201
        assert (
            client.get(
                "/api/v1/auth/session", headers={**headers, "Origin": "tauri://localhost"}
            ).status_code
            == 200
        )
        client.cookies.set(app.state.settings.cookie_name, "fake")
        assert client.get("/api/v1/auth/session", headers=headers).status_code == 400


def test_unknown_device_cannot_read_cancel_or_delete_another_devices_work():
    app, first = make_client(runner=FakeRunner(delay=1))
    second = TestClient(app, base_url=ORIGIN)
    with first:
        _auth, first_headers = pair(first, app)
        _auth, second_headers = pair(second, app, fresh=True)
        work = session(first, first_headers)
        job_id = submit(first, first_headers, work).json()["job_id"]
        assert (
            second.get(f"/api/v1/translations/{job_id}", headers=second_headers).status_code == 404
        )
        assert (
            second.post(
                f"/api/v1/translations/{job_id}/cancel", json={}, headers=second_headers
            ).status_code
            == 404
        )
        assert second.delete(f"/api/v1/sessions/{work}", headers=second_headers).status_code == 404


def test_idempotency_and_busy_limit():
    app, client = make_client(runner=FakeRunner(delay=1))
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        request_id = str(uuid4())
        one = submit(client, headers, work, request_id=request_id)
        two = submit(client, headers, work, request_id=request_id)
        assert one.json()["job_id"] == two.json()["job_id"]
        assert (
            submit(client, headers, work, text="Different", request_id=request_id).status_code
            == 409
        )
        assert submit(client, headers, work).status_code == 409


def test_clear_cancels_work_and_never_restores_text():
    runner = FakeRunner(delay=10)
    app, client = make_client(runner=runner)
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, job_id, {"running"})
        assert client.delete(f"/api/v1/sessions/{work}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/translations/{job_id}", headers=headers).status_code == 404
        assert runner.cancelled == 1 and runner.active == 0
        assert not app.state.jobs.jobs
    assert runner.closed
    assert not app.state.auth.active_device_ids()


def test_cancel_then_new_request_remains_single_concurrency():
    runner = FakeRunner(delay=10)
    app, client = make_client(runner=runner)
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, job_id, {"running"})
        assert (
            client.post(f"/api/v1/translations/{job_id}/cancel", json={}, headers=headers).json()[
                "status"
            ]
            == "cancelled"
        )
        runner.delay = 0
        next_job = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, next_job, {"succeeded"})
        assert runner.max_active == 1


def test_run_timeout_and_unknown_model_error_do_not_echo_input():
    settings = replace(ApiSettings(), run_timeout=0.03)
    runner = FakeRunner(delay=10)
    app, client = make_client(settings=settings, runner=runner)
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work, text="private-original-content").json()["job_id"]
        result = wait_status(client, headers, job_id, {"timed_out"})
        assert result["error"]["code"] == "TASK_TIMEOUT"
        assert result["result"] is None
        assert runner.cancelled == 1
        runner.delay, runner.fail = 0, True
        job_id = submit(client, headers, work).json()["job_id"]
        result = wait_status(client, headers, job_id, {"failed"})
        assert "private-original-content" not in str(result)


def test_result_and_auth_ttl_use_server_clock():
    clock = Clock()
    app, client = make_client(clock=clock)
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, job_id, {"succeeded"})
        clock.now += 301
        assert client.get(f"/api/v1/translations/{job_id}", headers=headers).status_code == 404
        clock.now += 1801
        assert client.get("/api/v1/auth/session", headers=headers).status_code == 401


def test_logout_revokes_token_and_purges_work():
    app, client = make_client(runner=FakeRunner(delay=10))
    with client:
        _auth, headers = pair(client, app, mode="bearer")
        work = session(client, headers)
        submit(client, headers, work)
        assert client.delete("/api/v1/auth/session", headers=headers).status_code == 204
        assert client.get("/api/v1/auth/session", headers=headers).status_code == 401
        assert not app.state.jobs.jobs and not app.state.jobs.sessions


@pytest.mark.parametrize(
    "payload",
    [
        {"private-original-content": "secret"},
        {"session_id": "bad-private-original-content", "client_request_id": "bad", "request": {}},
    ],
)
def test_validation_errors_do_not_echo_private_inputs(payload):
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        response = client.post("/api/v1/translations", json=payload, headers=headers)
        assert response.status_code == 422
        assert "private-original-content" not in response.text


def test_content_limit_simple_form_json_and_query_rejections():
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        assert (
            client.post(
                "/api/v1/sessions",
                content="x" * 32769,
                headers={**headers, "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert (
            client.post("/api/v1/sessions", data={"any": "form"}, headers=headers).status_code
            == 415
        )
        response = client.post(
            "/api/v1/sessions",
            content="private invalid json",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422 and "private invalid json" not in response.text
        assert client.get("/api/v1/health?private=value").status_code == 400
        assert (
            client.post(
                "/api/v1/sessions", json={}, headers={**headers, "Content-Encoding": "gzip"}
            ).status_code
            == 415
        )


def test_glossary_optimistic_revision_and_capabilities():
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        current = client.get("/api/v1/glossary", headers=headers).json()
        body = {
            "revision": current["revision"],
            "entries": [
                {
                    "source": "API",
                    "target": "接口",
                    "target_language": "zh-Hans",
                }
            ],
        }
        assert client.put("/api/v1/glossary", json=body, headers=headers).status_code == 200
        assert client.put("/api/v1/glossary", json=body, headers=headers).status_code == 409
        result = client.get("/api/v1/capabilities", headers=headers).json()
        assert "zh-Hans" in result["target_languages"]
        assert result["limits"]["text_characters"] == 4000
        assert client.get("/api/v1/openapi.json", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.1.1:8765",
        "*",
        "null",
        "https://user:pass@example.com",
        "https://example.com/path",
    ],
)
def test_unsafe_public_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        ApiSettings(public_origin=origin)


def test_exception_after_handler_is_sanitized_without_rethrow_or_sensitive_logs(caplog):
    app, client = make_client()

    @app.get("/unexpected")
    async def unexpected():
        raise RuntimeError("SENSITIVE_ORIGINAL_DO_NOT_LOG")

    with client:
        response = client.get("/unexpected")
        assert response.status_code == 500
        assert "SENSITIVE_ORIGINAL_DO_NOT_LOG" not in response.text
        assert "SENSITIVE_ORIGINAL_DO_NOT_LOG" not in caplog.text
        assert "API_HANDLER_FAILED" in caplog.text


def test_openapi_contains_typed_responses_and_authentication_contract():
    app, _client = make_client()
    schema = app.openapi()
    components = schema["components"]["schemas"]
    assert {
        "JobView",
        "AgentResult",
        "PairView",
        "AuthView",
        "CapabilitiesView",
        "GlossaryView",
    } <= components.keys()
    operation = schema["paths"]["/api/v1/translations"]["post"]
    assert operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/JobView"
    )
    assert operation["security"] == [{"SessionCookie": []}, {"BearerAuth": []}]
    assert "security" not in schema["paths"]["/api/v1/pair/exchange"]["post"]


def test_queue_bound_queue_timeout_and_other_devices_run_serially():
    clock = Clock()
    runner = FakeRunner(delay=10)
    settings = replace(ApiSettings(), max_queued=1)
    app, client = make_client(settings=settings, runner=runner, clock=clock)
    with client:
        _auth, one = pair(client, app, mode="bearer")
        _auth, two = pair(client, app, mode="bearer", fresh=True)
        _auth, three = pair(client, app, mode="bearer", fresh=True)
        first = submit(client, one, session(client, one)).json()["job_id"]
        wait_status(client, one, first, {"running"})
        second = submit(client, two, session(client, two)).json()["job_id"]
        full = submit(client, three, session(client, three))
        assert full.status_code == 429 and full.headers["retry-after"] == "5"
        clock.now += 31
        expired = wait_status(client, two, second, {"timed_out"})
        assert expired["error"]["code"] == "QUEUE_TIMEOUT"
        assert runner.calls == 1 and runner.max_active == 1


def test_session_expiry_stops_running_work_and_drops_all_content():
    clock = Clock()
    runner = FakeRunner(delay=10)
    settings = replace(ApiSettings(), session_ttl=10)
    app, client = make_client(settings=settings, runner=runner, clock=clock)
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, job_id, {"running"})
        clock.now += 11
        deadline = time.monotonic() + 2
        while app.state.jobs.jobs and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not app.state.jobs.sessions and not app.state.jobs.jobs
        assert runner.cancelled == 1


def test_chunked_body_without_content_length_is_still_bounded():
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        response = client.post(
            "/api/v1/sessions",
            content=iter([b"a" * 20000, b"b" * 20000]),
            headers={
                **headers,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 413
        response = client.post(
            "/api/v1/sessions",
            content=b"{}",
            headers={
                **headers,
                "Content-Type": "application/json",
                "Content-Length": "1",
            },
        )
        assert response.status_code == 400


def test_ambiguous_security_headers_and_duplicate_session_cookie_are_rejected():
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        assert (
            client.get(
                "/api/v1/health", headers=[("Host", "127.0.0.1:8765"), ("Host", "evil.example")]
            ).status_code
            == 400
        )
        name = app.state.settings.cookie_name
        token = client.cookies.get(name)
        assert (
            client.get(
                "/api/v1/auth/session", headers={"Cookie": f"{name}={token}; {name}={token}"}
            ).status_code
            == 400
        )
        assert (
            client.get("/api/v1/auth/session", headers={**headers, "Origin": "null"}).status_code
            == 403
        )


def test_native_allowlist_cannot_reuse_browser_cookie():
    app, client = make_client(settings=ApiSettings(client_origins=("tauri://localhost",)))
    with client:
        pair(client, app)
        response = client.get("/api/v1/auth/session", headers={"Origin": "tauri://localhost"})
        assert response.status_code == 403
        assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_cors_preflight_only_allows_explicit_origins_methods_and_headers():
    app, client = make_client(settings=ApiSettings(client_origins=("https://localhost",)))
    with client:
        response = client.options(
            "/api/v1/translations",
            headers={
                "Origin": "https://localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://localhost"
        assert "*" not in response.headers["access-control-allow-headers"]
        assert (
            client.options(
                "/api/v1/translations",
                headers={
                    "Origin": "https://localhost",
                    "Access-Control-Request-Method": "PATCH",
                },
            ).status_code
            == 400
        )


def test_closing_application_cancels_active_runner_and_empties_all_stores():
    runner = FakeRunner(delay=10)
    app, client = make_client(runner=runner)
    with client:
        _auth, headers = pair(client, app)
        job_id = submit(client, headers, session(client, headers)).json()["job_id"]
        wait_status(client, headers, job_id, {"running"})
    assert runner.closed and runner.cancelled == 1 and runner.active == 0
    assert not app.state.auth.active_device_ids()
    assert not app.state.jobs.jobs and not app.state.jobs.sessions


def test_submission_rate_limit_is_device_scoped_and_resets_by_clock():
    clock = Clock()
    app, client = make_client(
        settings=replace(ApiSettings(), submissions_per_minute=1), clock=clock
    )
    with client:
        _auth, headers = pair(client, app)
        work = session(client, headers)
        job_id = submit(client, headers, work).json()["job_id"]
        wait_status(client, headers, job_id, {"succeeded"})
        response = submit(client, headers, work)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "REQUEST_RATE_LIMIT"
        clock.now += 61
        assert submit(client, headers, work).status_code == 202


def test_refresh_recycles_only_never_used_sessions():
    app, client = make_client()
    with client:
        _auth, headers = pair(client, app)
        original = [session(client, headers) for _ in range(4)]
        replacement = session(client, headers)
        assert replacement not in original
        assert len(app.state.jobs.sessions) == 4
        assert original[0] not in app.state.jobs.sessions
        assert submit(client, headers, original[0]).status_code == 404
        used = original[1]
        job_id = submit(client, headers, used).json()["job_id"]
        wait_status(client, headers, job_id, {"succeeded"})
        session(client, headers)
        session(client, headers)
        assert used in app.state.jobs.sessions


def test_authenticated_api_burst_rate_is_per_device_and_clock_refills():
    clock = Clock()
    settings = replace(ApiSettings(), authenticated_burst=2, authenticated_per_minute=120)
    app, client = make_client(settings=settings, clock=clock)
    with client:
        _auth, one = pair(client, app, mode="bearer")
        _auth, two = pair(client, app, mode="bearer", fresh=True)
        for _ in range(2):
            assert client.get("/api/v1/auth/session", headers=one).status_code == 200
        blocked = client.get("/api/v1/auth/session", headers=one)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "AUTH_RATE_LIMIT"
        assert blocked.headers["retry-after"] == "5"
        assert client.get("/api/v1/auth/session", headers=two).status_code == 200
        clock.now += 1
        assert client.get("/api/v1/auth/session", headers=one).status_code == 200
