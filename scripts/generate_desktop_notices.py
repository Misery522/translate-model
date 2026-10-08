"""复用 cargo-about 生成可追溯的 Windows 许可待审查材料，不授予发布许可。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TARGET = "x86_64-pc-windows-msvc"
FILE_LIMIT = 2 * 1024 * 1024
LEGAL_NAME = re.compile(r"^(?:licen[cs]e|copying|notice|copyright)(?:[._-].*)?$", re.I)
PRIVATE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:Users|home)/|manifest_path|source_path")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or ":" in value:
        raise ValueError("unsafe material path")
    if any(part in {"", ".", ".."} or part.rstrip(" .") != part for part in value.split("/")):
        raise ValueError("unsafe material path")
    return value


def register_material_path(index: dict[str, str], artifact: str) -> None:
    """Windows 大小写别名（含目录）必须在写盘前拒绝，不能静默覆盖法律原文。"""
    safe_relative(artifact)
    parts = artifact.split("/")
    for length in range(1, len(parts) + 1):
        prefix = "/".join(parts[:length])
        normalized = prefix.casefold()
        if normalized in index and index[normalized] != prefix:
            raise ValueError("Windows material path alias collision")
        index[normalized] = prefix


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid public source URL")
    return value


def decode_material(data: bytes) -> str:
    if not data or len(data) > FILE_LIMIT:
        raise ValueError("empty or oversized legal material")
    text = data.decode("utf-8", errors="strict")
    if PRIVATE.search(text):
        raise ValueError("private metadata must not enter review materials")
    return text


def locked_packages(lockfile: Path) -> dict[tuple[str, str], dict]:
    result = {}
    for package in tomllib.loads(lockfile.read_text(encoding="utf-8"))["package"]:
        key = package["name"], package["version"]
        if key in result:
            raise ValueError("duplicate locked package")
        if package["name"] != "yijing-desktop" and (
            package.get("source") != "registry+https://github.com/rust-lang/crates.io-index"
            or re.fullmatch(r"[a-f0-9]{64}", package.get("checksum", "")) is None
        ):
            raise ValueError("unverified package source")
        result[key] = package
    return result


def actual_graph(output: str) -> set[tuple[str, str]]:
    result = set()
    for line in output.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_-]+) v([0-9][A-Za-z0-9.+_-]*)(?: .*)?", line)
        if match is None:
            raise ValueError("unexpected cargo tree record")
        if match[1] != "yijing-desktop":
            result.add((match[1], match[2]))
    return result


def archive_for(package: dict) -> Path:
    root = Path(package["manifest_path"]).parent
    if root.name != f"{package['name']}-{package['version']}":
        raise ValueError("package archive location mismatch")
    if root.parent.parent.name != "src" or root.parent.parent.parent.name != "registry":
        raise ValueError("unsupported Cargo cache layout")
    return root.parent.parent.parent / "cache" / root.parent.name / (root.name + ".crate")


def collect_materials(
    raw: dict,
    locked: dict,
    graph: set,
    fallback: dict,
    fallback_root: Path,
    policy: dict,
    policy_root: Path,
    runtime_graph: set | None = None,
) -> tuple[dict, dict[str, bytes]]:
    """只从已锁定原包和已核验补材取原文；不把通用回退文本当完整许可证。"""
    packages = {}
    for entry in raw["crates"]:
        package = entry["package"]
        key = package["name"], package["version"]
        if key in packages or key not in locked:
            raise ValueError("duplicate or unlocked cargo-about package")
        packages[key] = package
    if set(packages) != graph:
        raise ValueError("actual Windows graph and license collection differ")
    supplements = {(item["name"], item["version"]): item for item in fallback["crates"]}
    files: dict[str, bytes] = {}
    normalized_paths: dict[str, str] = {}
    records = []
    for key, package in sorted(packages.items()):
        name, version = key
        if re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
            raise ValueError("unsafe package name")
        if re.fullmatch(r"[0-9][A-Za-z0-9.+_-]*", version) is None:
            raise ValueError("unsafe package version")
        label = f"{name}@{version}"
        archive = archive_for(package)
        checksum = locked[key]["checksum"]
        if digest(archive) != checksum:
            raise ValueError("package checksum mismatch")
        record = {
            "name": name,
            "version": version,
            "declared_spdx": package["license"],
            "proposed_choice": policy["proposed_license_choices"].get(label, package["license"]),
            "package_sha256": checksum,
            "materials": [],
            "source_archive_url": f"https://static.crates.io/crates/{name}/{name}-{version}.crate",
            "graph_scope": "not-classified"
            if runtime_graph is None
            else (
                "normal-graph-candidate" if key in runtime_graph else "build-or-proc-macro-graph"
            ),
            "review_status": "requires-human-review",
            "review_points": ["核实实际分发范围、许可分支与完整版权/NOTICE。"],
        }

        def add(
            relative: str, data: bytes, source: dict, *, owner: str = label, entry: dict = record
        ) -> None:
            relative = safe_relative(relative)
            decode_material(data)
            artifact = f"{owner}/{relative}"
            register_material_path(normalized_paths, artifact)
            if artifact in files:
                if files[artifact] != data:
                    raise ValueError("conflicting legal material")
                return
            source = {
                field: source[field]
                for field in (
                    "kind",
                    "url",
                    "package_path",
                    "commit",
                    "git_blob_sha1",
                    "full_file_sha256",
                    "extracted_byte_range",
                )
                if field in source
            }
            public_url(source["url"])
            files[artifact] = data
            entry["materials"].append(
                {
                    "file": artifact,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "source": source,
                }
            )

        with tarfile.open(archive, "r:gz") as stream:
            prefix = f"{name}-{version}/"
            for member in stream.getmembers():
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                relative = safe_relative(member.name.removeprefix(prefix))
                if LEGAL_NAME.fullmatch(PurePosixPath(relative).name) is None:
                    continue
                if member.size > FILE_LIMIT:
                    raise ValueError("oversized archive legal material")
                extracted = stream.extractfile(member)
                if extracted is None:
                    raise ValueError("missing archive material")
                add(
                    relative,
                    extracted.read(FILE_LIMIT + 1),
                    {
                        "kind": "verified-crates-io-package",
                        "package_path": relative,
                        "url": f"https://static.crates.io/crates/{name}/{name}-{version}.crate",
                    },
                )
            # 保留工具识别的原包内嵌许可，例如复制代码的额外版权头。
            # 只取属于当前原包且逐字节可验证的源文件，不采用别的包的借用版权。
            crate_root = Path(package["manifest_path"]).resolve().parent
            for license_record in raw.get("licenses", []):
                source_path = license_record.get("source_path")
                if not source_path:
                    continue
                source_file = Path(source_path).resolve()
                if not source_file.is_relative_to(crate_root):
                    continue
                relative = safe_relative(source_file.relative_to(crate_root).as_posix())
                if LEGAL_NAME.fullmatch(PurePosixPath(relative).name):
                    continue
                member = stream.getmember(prefix + relative)
                if not member.isfile() or member.size > FILE_LIMIT:
                    raise ValueError("invalid inline license source")
                extracted = stream.extractfile(member)
                if extracted is None:
                    raise ValueError("missing inline license source")
                add(
                    "INLINE-LICENSES/" + relative,
                    extracted.read(FILE_LIMIT + 1),
                    {
                        "kind": "verified-package-inline-legal-source",
                        "package_path": relative,
                        "url": f"https://static.crates.io/crates/{name}/{name}-{version}.crate",
                    },
                )
        supplement = supplements.get(key)
        if supplement:
            if supplement["package_sha256"] != checksum:
                raise ValueError("supplement package checksum mismatch")
            for item in supplement["files"]:
                relative = safe_relative(item["artifact_path"])
                if not relative.startswith(label + "/"):
                    raise ValueError("supplement belongs to another package")
                material = fallback_root / relative
                if not material.resolve().is_relative_to(fallback_root.resolve()):
                    raise ValueError("supplement location escaped review root")
                if digest(material) != item["sha256"]:
                    raise ValueError("supplement material checksum mismatch")
                add(relative.removeprefix(label + "/"), material.read_bytes(), item["source"])
            record["review_points"].extend(supplement["review_points"])
        canonical_ids = []
        if key == ("siphasher", "1.0.3"):
            canonical_ids.append("Apache-2.0")
            record["review_points"].append("保留 COPYING 真实两作者版权，并提议 Apache 分支。")
        if package["license"] == "MPL-2.0":
            canonical_ids.append("MPL-2.0")
            record["review_points"].append(
                "区分构建期与实际分发；如内嵌，告知接收者取得该版本 MPL 源码的方式。"
            )
        for identifier in canonical_ids:
            canonical = policy["canonical_licenses"][identifier]
            material = policy_root / safe_relative(canonical["file"])
            if digest(material) != canonical["sha256"]:
                raise ValueError("canonical license checksum mismatch")
            add(
                "CANONICAL-" + canonical["file"],
                material.read_bytes(),
                {
                    "kind": "official-canonical-license",
                    "url": canonical["url"],
                },
            )
        if not record["materials"]:
            raise ValueError("package has no verifiable legal material")
        records.append(record)
    return {
        "schema_version": 1,
        "purpose": "private-review-materials-not-release-approval",
        "target": TARGET,
        "cargo_lock_sha256": policy["cargo_lock_sha256"],
        "crate_count": len(records),
        "material_file_count": len(files),
        "compliance_review_passed": False,
        "crates": records,
    }, files


def tool(command: list[str], env: dict) -> bytes:
    try:
        result = subprocess.run(command, env=env, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("license tool failed or exceeded 60s") from None
    if result.returncode != 0:
        raise ValueError("license tool returned nonzero")
    return result.stdout


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cargo-about", type=Path, required=True)
    parser.add_argument("--cargo", type=Path, required=True)
    parser.add_argument("--fallback-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    allowed_output = ROOT.resolve() / "artifacts"
    if (
        allowed_output.resolve() != allowed_output
        or output == allowed_output
        or not output.is_relative_to(allowed_output)
        or output.exists()
    ):
        raise ValueError("output must be a new directory under project artifacts")
    policy_root = ROOT / "desktop/licenses"
    policy = json.loads((policy_root / "material-policy.json").read_text(encoding="utf-8"))
    lockfile = ROOT / "desktop/src-tauri/Cargo.lock"
    lock_hash = digest(lockfile)
    if lock_hash != policy["cargo_lock_sha256"]:
        raise ValueError("Cargo.lock changed; renew material review")
    if digest(args.fallback_manifest) != policy["fallback_manifest_sha256"]:
        raise ValueError("fallback manifest checksum mismatch")
    fallback = json.loads(args.fallback_manifest.read_text(encoding="utf-8"))
    if fallback["cargo_lock_sha256"] != lock_hash:
        raise ValueError("fallback belongs to another lockfile")
    env = {**os.environ, "RUSTUP_TOOLCHAIN": "1.98.0-x86_64-pc-windows-msvc"}
    env["PATH"] = str(args.cargo.resolve().parent) + os.pathsep + env.get("PATH", "")
    if tool([str(args.cargo_about), "--version"], env).decode().strip() != "cargo-about 0.9.2":
        raise ValueError("unexpected cargo-about version")
    manifest = str(ROOT / "desktop/src-tauri/Cargo.toml")
    # cargo-about 在 Windows 会拒绝重定向 stdout；使用其正式输出参数。
    # 私有元数据留在忽略目录，不把包含 registry 本机路径的 JSON 当公开清单。
    (ROOT / "artifacts").mkdir(exist_ok=True)
    raw_dir = Path(tempfile.mkdtemp(prefix="desktop-license-raw-", dir=ROOT / "artifacts"))
    raw_file = raw_dir / "cargo-about.private.json"
    tool(
        [
            str(args.cargo_about),
            "generate",
            "--manifest-path",
            manifest,
            "--config",
            str(policy_root / "about.toml"),
            "--locked",
            "--offline",
            "--fail",
            "--target",
            TARGET,
            "--format",
            "json",
            "--output-file",
            str(raw_file),
        ],
        env,
    )
    raw_bytes = raw_file.read_bytes()
    graph = actual_graph(
        tool(
            [
                str(args.cargo),
                "tree",
                "--manifest-path",
                manifest,
                "--locked",
                "--offline",
                "--target",
                TARGET,
                "--edges",
                "normal,build",
                "--prefix",
                "none",
                "--format",
                "{p}",
            ],
            env,
        ).decode("utf-8")
    )
    runtime_graph = actual_graph(
        tool(
            [
                str(args.cargo),
                "tree",
                "--manifest-path",
                manifest,
                "--locked",
                "--offline",
                "--target",
                TARGET,
                "--edges",
                "normal,no-proc-macro",
                "--prefix",
                "none",
                "--format",
                "{p}",
            ],
            env,
        ).decode("utf-8")
    )
    result, files = collect_materials(
        json.loads(raw_bytes),
        locked_packages(lockfile),
        graph,
        fallback,
        args.fallback_manifest.resolve().parent,
        policy,
        policy_root,
        runtime_graph,
    )
    if digest(lockfile) != lock_hash:
        raise ValueError("Cargo.lock changed during collection")
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    decode_material(rendered.encode("utf-8"))
    combined = ["仅供许可人工审查：材料覆盖不等于再分发许可通过。\n"]
    for record in result["crates"]:
        combined.append(f"\n{record['name']} {record['version']}\n")
        for item in record["materials"]:
            combined.append(f"\n材料：{item['file']}\n来源：{item['source']['url']}\n")
            combined.append(files[item["file"]].decode("utf-8"))
    # 全部校验通过后才写入新的忽略目录；从不覆盖旧材料或生成发布批准标记。
    output.mkdir(parents=True)
    for relative, data in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output / "manifest.json").write_text(rendered, encoding="utf-8")
    (output / "REVIEW_MATERIALS.txt").write_text("\n".join(combined), encoding="utf-8")
    print(
        f"Collected {len(result['crates'])} crates / {len(files)} materials; review NOT approved."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, UnicodeError, tarfile.TarError):
        raise SystemExit("Desktop license collection failed; no release approval.") from None
