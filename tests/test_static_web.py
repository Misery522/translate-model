from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yijing_api.static import mount_static_shell


@pytest.fixture
def static_client(tmp_path):
    (tmp_path / "index.html").write_text("<h1>译境</h1>", encoding="utf-8")
    (tmp_path / "sw.js").write_text("// static only", encoding="utf-8")
    (tmp_path / "private.txt").write_text("not public", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-123.js").write_text("void 0", encoding="utf-8")
    (tmp_path / "assets" / "app-123.js.map").write_text("{}", encoding="utf-8")
    app = FastAPI()
    mount_static_shell(app, tmp_path)
    with TestClient(app) as client:
        yield client


def test_static_shell_has_csp_and_no_inline_exceptions(static_client):
    response = static_client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_static_assets_cache_but_worker_revalidates(static_client):
    assert "immutable" in static_client.get("/assets/app-123.js").headers["cache-control"]
    assert static_client.get("/sw.js").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", [
    "/private.txt", "/assets/app-123.js.map", "/api/v1/missing", "/.env",
    "/assets/../private.txt", "/missing", "/assets/nested/app.js",
])
def test_static_server_exposes_only_public_build_files(static_client, path):
    assert static_client.get(path).status_code == 404


def test_static_shell_requires_build(tmp_path):
    with pytest.raises(ValueError):
        mount_static_shell(FastAPI(), Path(tmp_path))
