"""发布前检查 Git 快照；仅输出位置和问题类型，不输出疑似秘密。

默认检查整个暂存区；CI 使用 --scope tracked 检查 HEAD。
工作区未暂存修改、未跟踪文件和历史提交不属于本检查的范围。
该检查是可解释的发布门禁，不能替代人工审查或专业秘密扫描器。
源码、文档和其他文本必须使用 UTF-8；只允许明确列出的图像/字体二进制扩展名。
二进制素材的内容、元数据与来源仍需人工审查，扩展名许可不证明内容安全。
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_BINARY_ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
}
BLOCKED_PARTS = {
    ".venv", "venv", "__pycache__", ".ruff_cache", ".mypy_cache", ".ollama",
    "node_modules", "recordings", "logs", "blobs", "manifests", ".gradle",
    "target", "build", "dist",
}
BLOCKED_NAMES = {
    "glossary.json", "environment_inventory.md", "environment_acceptance_report.md",
    "cleanup_candidates.md", "local.properties", "id_rsa", "id_ed25519",
    "credentials.json", "service-account.json",
}
BLOCKED_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3",
    ".gguf", ".safetensors", ".onnx", ".pt", ".pth", ".bin",
    ".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".pcm",
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer",
    ".apk", ".aab", ".msi", ".exe", ".dmg", ".ipa",
}
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|"
                                r"github_pat_[A-Za-z0-9_]{80,255})\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("tailscale-key", re.compile(r"\btskey-(?:auth|api)-[A-Za-z0-9-]{20,}\b")),
    ("credential-url", re.compile(r"https?://[^\s/:@]+:[^\s/@]{8,}@")),
)
ASSIGNMENT = re.compile(
    r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"secret[_-]?key|password)\b[\"']?\s*[:=]\s*[\"']([^\"'\r\n]{24,})[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: str
    code: str
    line: int | None = None


def path_findings(path: str) -> list[Finding]:
    """固定运行数据、权重、录音、证书不应出现在公开源码快照中。"""
    name = PurePosixPath(path)
    parts = tuple(part.lower() for part in name.parts)
    basename = parts[-1]
    blocked = (
        any(part in BLOCKED_PARTS or part.startswith(".pytest") for part in parts)
        or any(part.endswith(".egg-info") for part in parts)
        or basename in BLOCKED_NAMES
        or (basename.startswith(".env") and basename != ".env.example")
        or name.suffix.lower() in BLOCKED_SUFFIXES
        or re.search(r"\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$", basename) is not None
    )
    return [Finding(path, "forbidden-path")] if blocked else []


def content_findings(path: str, content: bytes) -> list[Finding]:
    findings = path_findings(path)
    if len(content) > MAX_BYTES:
        return [*findings, Finding(path, "file-over-10-mib")]
    binary_asset_allowed = PurePosixPath(path).suffix.lower() in ALLOWED_BINARY_ASSET_SUFFIXES
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        if not binary_asset_allowed:
            findings.append(Finding(path, "unsupported-text-encoding"))
        return findings
    if "\x00" in source and not binary_asset_allowed:
        # 无 BOM 的 UTF-16 ASCII 文本也能被 UTF-8 解码；NUL 不得成为扫描绕过。
        return [*findings, Finding(path, "unsupported-text-encoding")]
    for code, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(source):
            findings.append(Finding(path, code, source.count("\n", 0, match.start()) + 1))
    for match in ASSIGNMENT.finditer(source):
        value = match.group(1)
        # 仅检测形似真实静态凭据的赋值；变量名、环境读取和示例占位符不报错。
        if any(word in value.lower() for word in ("example", "placeholder", "your_", "replace")):
            continue
        if (
            re.fullmatch(r"[A-Za-z0-9_+/=-]+", value)
            and len(set(value)) >= 12
            and sum(bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"\d"))
            == 3
        ):
            findings.append(
                Finding(path, "static-credential", source.count("\n", 0, match.start()) + 1)
            )
    return findings


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        check=True, capture_output=True, timeout=30,
    ).stdout


def audit_snapshot(root: Path, scope: str = "index") -> tuple[int, list[Finding]]:
    """从对象数据库读取提交内容，避免把未暂存的修复误认为已经安全。"""
    if scope not in {"index", "tracked"}:
        raise ValueError("scope must be index or tracked")
    command = ("ls-files", "--stage", "-z") if scope == "index" else (
        "ls-tree", "-r", "-z", "HEAD",
    )
    entries = [entry for entry in git(root, *command).split(b"\0") if entry]
    findings: list[Finding] = []
    for entry in entries:
        metadata, raw_path = entry.split(b"\t", 1)
        mode, second, third = metadata.decode("ascii").split()
        oid = second if scope == "index" else third
        path = raw_path.decode("utf-8", errors="replace")
        if mode not in {"100644", "100755"}:
            findings.append(Finding(path, "non-regular-git-entry"))
            continue
        if scope == "index" and third != "0":
            findings.append(Finding(path, "unmerged-index-entry"))
            continue
        size = int(git(root, "cat-file", "-s", oid))
        if size > MAX_BYTES:
            findings.extend([*path_findings(path), Finding(path, "file-over-10-mib")])
            continue
        findings.extend(content_findings(path, git(root, "cat-file", "blob", oid)))
    return len(entries), findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("index", "tracked"), default="index")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        count, findings = audit_snapshot(args.root, args.scope)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Publication audit could not read the Git snapshot; no files were approved.")
        return 2
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        print(f"{location}: {finding.code}")
    if findings:
        print(f"Publication audit failed: {len(findings)} finding(s) in {count} entries.")
        return 1
    print(f"Publication audit passed: {count} entries ({args.scope}); history not scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
