import sys

import pytest

from yijing_api import cli


def test_cli_starts_only_loopback_and_mounts_static(tmp_path, monkeypatch, capsys):
    (tmp_path / "index.html").write_text("<h1>Yijing</h1>", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["yijing-api", "--port", "18764", "--static-dir", str(tmp_path)])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    invocation = {}

    def capture_run(app, **kwargs):
        invocation.update(kwargs)
        assert app.routes[-1].name == "web"
        assert app.state.pairing_code is None

    monkeypatch.setattr(cli.uvicorn, "run", capture_run)
    cli.main()
    assert invocation["host"] == "127.0.0.1"
    assert invocation["port"] == 18764
    assert invocation["workers"] == 1
    assert invocation["access_log"] is False
    assert invocation["proxy_headers"] is False
    assert "网页界面已挂载" in capsys.readouterr().out


def test_cli_rejects_unbuilt_static_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yijing-api", "--static-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
