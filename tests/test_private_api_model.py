"""显式启用的本机模型验收；普通 CI 不下载或加载模型。"""

import os
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from yijing_api.app import create_app
from yijing_api.config import ApiSettings

pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(os.getenv("OLLAMA_INTEGRATION") != "1", reason="explicit local model opt-in"),
]


def test_private_api_pairs_and_runs_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("YIJING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    settings = ApiSettings(run_timeout=45)
    app = create_app(settings)
    with TestClient(app, base_url=settings.public_origin) as client:
        client.headers["Origin"] = settings.public_origin
        pair = client.post("/api/v1/pair/exchange", json={
            "code": app.state.pairing_code, "device_name": "Local integration test",
            "auth_mode": "cookie",
        })
        assert pair.status_code == 201
        assert pair.json()["access_token"] is None
        client.headers["X-CSRF-Token"] = pair.json()["csrf_token"]
        session = client.post("/api/v1/sessions", json={}).json()["session_id"]
        submitted = client.post("/api/v1/translations", json={
            "session_id": session, "client_request_id": str(uuid4()),
            "request": {
                "text": "Please send me the meeting notes.",
                "target_language": "zh-Hans", "task_mode": "translate",
            },
        })
        assert submitted.status_code == 202
        job_id = submitted.json()["job_id"]
        deadline = time.monotonic() + 48
        while time.monotonic() < deadline:
            job = client.get(f"/api/v1/translations/{job_id}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.5)
        assert job["status"] == "succeeded", job.get("error")
        result = job["result"]
        assert result["route"] == "translate_text"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in result["translated_text"])
        assert client.delete(f"/api/v1/sessions/{session}").status_code == 204
        assert client.get(f"/api/v1/translations/{job_id}").status_code == 404
        assert client.delete("/api/v1/auth/session").status_code == 204
        assert client.get("/api/v1/auth/session").status_code == 401
    assert app.state.jobs.runner.pid is None
