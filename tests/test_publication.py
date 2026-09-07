"""发布门禁必须检查 Git 中的真实内容，并避免泄露检测到的秘密。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.audit_publication import MAX_BYTES, audit_snapshot, content_findings, path_findings


@pytest.mark.parametrize("path", [
    "data/glossary.json", ".env", ".env.local", "voice/sample.wav", "model.gguf",
    "model.safetensors", "certs/release.pfx", ".venv/pyvenv.cfg", "data/app.sqlite3-wal",
    "environment_inventory.md", "models/blobs/sha256-abc", "app/build/output.txt",
])
def test_runtime_and_private_files_are_rejected(path: str) -> None:
    assert path_findings(path)


@pytest.mark.parametrize("path,source", [
    (".env.example", b"TRANSLATOR_KEEP_ALIVE=30m\n"),
    ("data/glossary.example.json", b"[]"),
    ("settings.py", b"token = os.environ.get('API_KEY')"),
    ("README.md", b"Use C:\\Users\\<username>\\project or /home/example/project."),
    ("config.py", b'api_key = "your_example_token_replace_before_using"'),
])
def test_public_examples_and_variable_names_are_allowed(path: str, source: bytes) -> None:
    assert content_findings(path, source) == []


def test_secret_detection_reports_location_without_echoing_value() -> None:
    secret = "ghp_" + "a" * 36
    findings = content_findings("config.py", f"# config\nTOKEN = '{secret}'".encode())
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].code == "github-token"
    assert secret not in repr(findings)


def test_private_key_and_static_credentials_are_detected() -> None:
    key_header = "-----BEGIN " + "RSA PRIVATE KEY-----"
    assert content_findings("unsafe.txt", key_header.encode())[0].code == "private-key"
    credential = "aBcD1234" * 4 + "efGhiJ567890"
    assert content_findings("settings.py", f'api_key = "{credential}"'.encode())


@pytest.mark.parametrize("prefix,length,code", [
    ("sk-proj-", 48, "openai-key"),
    ("AIza", 35, "google-api-key"),
    ("hf_", 32, "huggingface-token"),
    ("tskey-auth-", 32, "tailscale-key"),
])
def test_known_service_keys_are_detected(prefix: str, length: int, code: str) -> None:
    findings = content_findings("config.txt", (prefix + "b" * length).encode())
    assert any(finding.code == code for finding in findings)


def test_large_file_is_rejected_before_decoding() -> None:
    assert content_findings("asset.dat", b"\x00" * (MAX_BYTES + 1))[0].code == "file-over-10-mib"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
@pytest.mark.parametrize("path", ["settings.py", "README.md", ".env.example", "config.unknown"])
def test_non_utf8_text_cannot_bypass_secret_scanning(path: str, encoding: str) -> None:
    secret = "ghp_" + "a" * 36
    findings = content_findings(path, f"TOKEN = '{secret}'".encode(encoding))
    assert any(finding.code == "unsupported-text-encoding" for finding in findings)
    assert secret not in repr(findings)


@pytest.mark.parametrize("path", ["data.dat", "README.md", "image.svg", "unknown"])
def test_unknown_binary_and_non_utf8_svg_are_rejected(path: str) -> None:
    assert content_findings(path, b"\xff\xfe\x00")[0].code == "unsupported-text-encoding"


@pytest.mark.parametrize("path", ["pet.png", "pet.webp", "font.woff2", "icon.ICO"])
def test_explicit_binary_assets_remain_subject_to_size_and_path_gates(path: str) -> None:
    assert content_findings(path, b"\x89\xff\x00") == []
    assert content_findings(f"recordings/{path}", b"\x89\xff\x00")[0].code == "forbidden-path"
    assert content_findings(path, b"\xff" * (MAX_BYTES + 1))[0].code == "file-over-10-mib"


def test_utf8_bom_does_not_hide_credentials() -> None:
    secret = "ghp_" + "a" * 36
    assert content_findings("settings.py", secret.encode("utf-8-sig"))[0].code == "github-token"


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=10)


def test_index_reads_staged_blob_not_later_working_copy(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    path = tmp_path / "settings.py"
    path.write_text("TOKEN = '" + "ghp_" + "b" * 36 + "'", encoding="utf-8")
    run_git(tmp_path, "add", "settings.py")
    path.write_text("TOKEN = None", encoding="utf-8")
    count, findings = audit_snapshot(tmp_path)
    assert count == 1
    assert findings[0].code == "github-token"
    run_git(tmp_path, "add", "settings.py")
    assert audit_snapshot(tmp_path) == (1, [])


def test_tracked_scope_reads_head_and_does_not_claim_untracked_files(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    (tmp_path / "safe.py").write_text("VALUE = 1", encoding="utf-8")
    run_git(tmp_path, "add", "safe.py")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "test")
    (tmp_path / ".env").write_text("PRIVATE=local", encoding="utf-8")
    run_git(tmp_path, "add", ".env")
    assert audit_snapshot(tmp_path, "tracked") == (1, [])
    assert audit_snapshot(tmp_path, "index")[1][0].code == "forbidden-path"
