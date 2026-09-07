"""检查 wheel 与 sdist 的完整性，在临时目录验证导入及源码包离线单测。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

RUNTIME_MODULES = (
    "agent", "smoke_model", "yijing.__init__", "yijing.paths", "yijing.glossary",
    "yijing.translation", "yijing.workflow", "yijing.service",
    "yijing_api.__init__", "yijing_api.app", "yijing_api.auth", "yijing_api.config",
    "yijing_api.cli", "yijing_api.errors", "yijing_api.jobs", "yijing_api.models",
    "yijing_api.worker", "yijing_api.static",
)
RUNTIME_PATHS = {module.replace(".", "/") + ".py" for module in RUNTIME_MODULES}
REQUIRED_SOURCE = {
    *RUNTIME_PATHS,
    "pyproject.toml", "uv.lock", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "README.md", "PRIVACY.md", "SECURITY.md", "THREAT_MODEL.md", "CONTRIBUTING.md",
    ".env.example", ".python-version", "MANIFEST.in",
    "scripts/audit_publication.py", "scripts/verify_distributions.py",
    "scripts/export_openapi.py",
    "data/glossary.example.json", "docs/ROADMAP.md",
    "tests/test_publication.py", "tests/test_smoke_model.py",
}


def validate_archive_paths(names: list[str]) -> None:
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError(f"Unsafe archive member: {name}")


def validate_wheel_members(names: list[str]) -> None:
    validate_archive_paths(names)
    missing = RUNTIME_PATHS - set(names)
    for license_name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if not any(name.endswith(f".dist-info/licenses/{license_name}") for name in names):
            missing.add(license_name)
    if missing:
        raise ValueError(f"Wheel missing required files: {', '.join(sorted(missing))}")


def validate_source_members(names: list[str]) -> str:
    validate_archive_paths(names)
    roots = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
    if len(roots) != 1:
        raise ValueError("Source archive must contain exactly one root directory")
    root = roots.pop()
    relative = {name.removeprefix(root + "/") for name in names}
    missing = REQUIRED_SOURCE - relative
    if missing:
        raise ValueError(f"Source archive missing required files: {', '.join(sorted(missing))}")
    return root


def verification_code(root: Path, *, run_tests: bool) -> str:
    # 强制检查所有业务模块来自解包目录，防止旧 editable 安装掩盖缺失文件。
    code = (
        "import importlib, pathlib, sys; "
        f"root=pathlib.Path({str(root)!r}).resolve(); sys.path.insert(0,str(root)); "
        f"modules=[importlib.import_module(name) for name in {RUNTIME_MODULES!r}]; "
        "assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) for m in modules); "
    )
    if run_tests:
        code += "import pytest; sys.exit(pytest.main(['-q','-m','not ollama']))"
    else:
        code += "print('Wheel imports verified from extracted artifact')"
    return code


def verify_distributions(dist_directory: Path) -> None:
    wheels = list(dist_directory.glob("*.whl"))
    sources = list(dist_directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source archive in --dist-dir")
    environment = os.environ.copy()
    environment.update({
        "GRADIO_ANALYTICS_ENABLED": "False", "DO_NOT_TRACK": "1",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434", "OLLAMA_MODEL": "qwen3.5:4b",
    })
    environment.pop("OLLAMA_INTEGRATION", None)
    environment.pop("TRANSLATOR_KEEP_ALIVE", None)
    with tempfile.TemporaryDirectory(prefix="yijing-artifact-check-") as temporary:
        temporary_root = Path(temporary)
        environment["YIJING_DATA_DIR"] = str(temporary_root / "private-data")
        wheel_root = temporary_root / "wheel"
        wheel_root.mkdir()
        with zipfile.ZipFile(wheels[0]) as wheel:
            validate_wheel_members(wheel.namelist())
            wheel.extractall(wheel_root)
        subprocess.run(
            [sys.executable, "-I", "-c", verification_code(wheel_root, run_tests=False)],
            cwd=wheel_root, env=environment, check=True, timeout=60,
        )
        source_root = temporary_root / "source"
        source_root.mkdir()
        with tarfile.open(sources[0]) as source:
            root_name = validate_source_members(source.getnames())
            if any(not (member.isfile() or member.isdir()) for member in source.getmembers()):
                raise ValueError("Source archive must contain only files and directories")
            source.extractall(source_root, filter="data")
        extracted = source_root / root_name
        subprocess.run(
            [sys.executable, "-I", "-c", verification_code(extracted, run_tests=True)],
            cwd=extracted, env=environment, check=True, timeout=60,
        )
    print("Distribution verification passed (wheel imports and isolated sdist tests).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        verify_distributions(args.dist_dir)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"Distribution verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
