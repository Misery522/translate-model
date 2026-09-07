from pathlib import Path

import app_paths


def test_source_checkout_keeps_local_glossary(tmp_path, monkeypatch):
    monkeypatch.delenv("YIJING_DATA_DIR", raising=False)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert app_paths.data_directory(tmp_path / "app_paths.py") == tmp_path / "data"


def test_wheel_uses_user_data_not_site_packages(tmp_path, monkeypatch):
    monkeypatch.delenv("YIJING_DATA_DIR", raising=False)
    user_data = tmp_path / "user-data"
    monkeypatch.setattr(app_paths, "user_data_path", lambda *a, **k: user_data)
    assert app_paths.data_directory(Path("site-packages/app_paths.py")) == user_data


def test_explicit_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("YIJING_DATA_DIR", str(tmp_path / "private"))
    assert app_paths.data_directory() == tmp_path / "private"
