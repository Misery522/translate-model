"""桌面许可采集只产生待审查材料，不能将源码元数据或工具成功当作发布许可。"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import generate_desktop_notices as notices


def fixture_package(
    tmp_path: Path,
    *,
    name: str = "example",
    version: str = "1.0.0",
    license_text: bytes = b"Copyright 2026 Example\nFull fixture license\n",
    extra_materials: dict[str, bytes] | None = None,
) -> tuple:
    index = "index.crates.io-fixture"
    directory = f"{name}-{version}"
    root = tmp_path / "registry/src" / index / directory
    root.mkdir(parents=True)
    archive = tmp_path / "registry/cache" / index / (directory + ".crate")
    archive.parent.mkdir(parents=True, exist_ok=True)
    materials = {
        "LICENSE": license_text,
        "NOTICE": b"Actual extra attribution\n",
        "src/inline.rs": b"// Copyright Actual copied code\n",
    }
    materials.update(extra_materials or {})
    with tarfile.open(archive, "w:gz") as stream:
        for relative, content in materials.items():
            item = tarfile.TarInfo(f"{directory}/{relative}")
            item.size = len(content)
            stream.addfile(item, io.BytesIO(content))
    package = {
        "name": name,
        "version": version,
        "license": "MIT",
        "manifest_path": str(root / "Cargo.toml"),
        "private_field": "never-export",
    }
    raw = {
        "crates": [{"package": package}],
        "licenses": [
            {
                "source_path": str(root / "src/inline.rs"),
                "text": "must use original archive bytes",
            }
        ],
    }
    locked = {(name, version): {"checksum": notices.digest(archive)}}
    policy = {
        "cargo_lock_sha256": "fixture-lock",
        "proposed_license_choices": {},
        "canonical_licenses": {},
    }
    return raw, locked, {(name, version)}, {"crates": []}, tmp_path, policy, tmp_path


def test_collect_preserves_all_legal_text_and_inline_copyright_without_private_metadata(
    tmp_path: Path,
) -> None:
    result, files = notices.collect_materials(*fixture_package(tmp_path))
    assert result["crate_count"] == 1
    assert result["material_file_count"] == 3
    assert result["compliance_review_passed"] is False
    record = result["crates"][0]
    assert record["review_status"] == "requires-human-review"
    assert (
        record["source_archive_url"]
        == "https://static.crates.io/crates/example/example-1.0.0.crate"
    )
    assert files["example@1.0.0/NOTICE"] == b"Actual extra attribution\n"
    assert files["example@1.0.0/INLINE-LICENSES/src/inline.rs"].startswith(b"// Copyright Actual")
    rendered = json.dumps(result)
    assert "manifest_path" not in rendered and "source_path" not in rendered
    assert str(tmp_path) not in rendered and "never-export" not in rendered


@pytest.mark.parametrize("mutation", ["duplicate", "missing-graph", "unlocked", "bad-checksum"])
def test_collection_rejects_graph_and_integrity_mismatches(tmp_path: Path, mutation: str) -> None:
    args = list(fixture_package(tmp_path))
    if mutation == "duplicate":
        args[0]["crates"].append(args[0]["crates"][0])
    elif mutation == "missing-graph":
        args[2] = set()
    elif mutation == "unlocked":
        args[1] = {}
    else:
        args[1][("example", "1.0.0")]["checksum"] = "0" * 64
    with pytest.raises(ValueError):
        notices.collect_materials(*args)


def test_normal_graph_classification_does_not_claim_actual_binary_embedding(tmp_path: Path) -> None:
    args = fixture_package(tmp_path)
    candidate, _ = notices.collect_materials(*args, runtime_graph={("example", "1.0.0")})
    build, _ = notices.collect_materials(*args, runtime_graph=set())
    assert candidate["crates"][0]["graph_scope"] == "normal-graph-candidate"
    assert build["crates"][0]["graph_scope"] == "build-or-proc-macro-graph"
    assert candidate["compliance_review_passed"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"license": b"Different legal material\n"},
        {"LiCeNsE": b"Copyright 2026 Example\nFull fixture license\n"},
        {"folder/LICENSE": b"One\n", "Folder/NOTICE": b"Two\n"},
        {"sub/NOTICE": b"One\n", "SUB/NOTICE": b"One\n"},
    ],
)
def test_windows_material_aliases_are_rejected_before_any_output_write(
    tmp_path: Path,
    extra: dict[str, bytes],
) -> None:
    args = fixture_package(tmp_path, extra_materials=extra)
    with pytest.raises(ValueError, match="Windows material path alias collision"):
        notices.collect_materials(*args)
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize(
    "path", ["LICENSE.", "NOTICE ", "directory./COPYRIGHT", "directory /LICENSE"]
)
def test_windows_trailing_dot_and_space_aliases_are_rejected(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe material path"):
        notices.safe_relative(path)


def test_siphasher_keeps_original_notice_and_adds_full_official_terms(tmp_path: Path) -> None:
    copying = b"Copyright Real One\nCopyright Real Two\nLicensed under Apache or MIT.\n"
    args = list(fixture_package(tmp_path, name="siphasher", version="1.0.3", license_text=copying))
    canonical = tmp_path / "Apache-2.0.txt"
    canonical.write_bytes(b"Complete canonical fixture license\n")
    args[5]["canonical_licenses"]["Apache-2.0"] = {
        "file": canonical.name,
        "sha256": notices.digest(canonical),
        "url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    }
    args[5]["proposed_license_choices"]["siphasher@1.0.3"] = "Apache-2.0"
    result, files = notices.collect_materials(*args)
    assert files["siphasher@1.0.3/LICENSE"] == copying
    assert files["siphasher@1.0.3/CANONICAL-Apache-2.0.txt"] == canonical.read_bytes()
    assert result["crates"][0]["proposed_choice"] == "Apache-2.0"
    assert result["crates"][0]["review_status"] == "requires-human-review"
    canonical.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="canonical license checksum mismatch"):
        notices.collect_materials(*args)


def test_supplement_is_checksum_bound_and_does_not_override_original(tmp_path: Path) -> None:
    args = list(fixture_package(tmp_path))
    supplement = tmp_path / "example@1.0.0/SOURCE_HEADER.txt"
    supplement.parent.mkdir()
    supplement.write_bytes(b"Actual additional copyright\n")
    args[3]["crates"] = [
        {
            "name": "example",
            "version": "1.0.0",
            "review_points": ["Needs human review"],
            "package_sha256": args[1][("example", "1.0.0")]["checksum"],
            "files": [
                {
                    "artifact_path": "example@1.0.0/SOURCE_HEADER.txt",
                    "sha256": notices.digest(supplement),
                    "source": {
                        "kind": "verified-source",
                        "url": "https://github.com/example/example",
                        "manifest_path": "never-export",
                        "commit": "a" * 40,
                    },
                }
            ],
        }
    ]
    result, files = notices.collect_materials(*args)
    assert files["example@1.0.0/SOURCE_HEADER.txt"] == supplement.read_bytes()
    assert "never-export" not in json.dumps(result)
    supplement.write_bytes(b"changed")
    with pytest.raises(ValueError, match="supplement material checksum mismatch"):
        notices.collect_materials(*args)


@pytest.mark.parametrize(
    "value",
    ["../secret", "/secret", "a/../secret", "a\\secret", "C:/secret", "a//secret", "a/./secret"],
)
def test_material_paths_reject_traversal_and_absolute_locations(value: str) -> None:
    with pytest.raises(ValueError, match="unsafe material path"):
        notices.safe_relative(value)


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"\xff",
        b"source_path=C:\\Users\\private",
        b"private /home/user/registry",
        b"C:/Users/private",
    ],
)
def test_material_decode_fails_on_invalid_or_private_data(value: bytes) -> None:
    with pytest.raises((ValueError, UnicodeError)):
        notices.decode_material(value)


def test_public_https_sources_are_not_mistaken_for_windows_drive_paths() -> None:
    assert notices.decode_material(b"https://www.apache.org/licenses/LICENSE-2.0")
    with pytest.raises(ValueError):
        notices.public_url("https://user:secret@example.com/LICENSE")


def test_graph_parser_includes_proc_macros_and_rejects_unknown_output() -> None:
    assert notices.actual_graph(
        "yijing-desktop v1.0.0 (/project)\nexample v1.0.0 (proc-macro)\n"
    ) == {("example", "1.0.0")}
    with pytest.raises(ValueError):
        notices.actual_graph("private diagnostic, not a dependency")


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired(["secret"], 60), OSError("private tool path")]
)
def test_tool_uses_60_second_limit_and_does_not_expose_exception(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def fail(*_args: object, **options: object) -> None:
        assert options["timeout"] == 60
        assert options["capture_output"] is True
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="^license tool failed or exceeded 60s$"):
        notices.tool(["tool"], {})


def test_repository_policy_has_real_full_terms_and_no_approval_flag() -> None:
    root = notices.ROOT / "desktop/licenses"
    policy = json.loads((root / "material-policy.json").read_text(encoding="utf-8"))
    assert policy["compliance_review_passed"] is False
    for item in policy["canonical_licenses"].values():
        assert hashlib.sha256((root / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    apache = (root / "Apache-2.0.txt").read_text(encoding="utf-8")
    mpl = (root / "MPL-2.0.txt").read_text(encoding="utf-8")
    assert "END OF TERMS AND CONDITIONS" in apache and "APPENDIX:" in apache
    assert "3.2. Distribution of Executable Form" in mpl and "Exhibit B" in mpl


@pytest.mark.parametrize("existing", [False, True])
def test_cli_rejects_unsafe_or_existing_output_before_tool_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    monkeypatch.setattr(notices, "ROOT", tmp_path)
    output = tmp_path / ("artifacts/existing" if existing else "outside")
    if existing:
        output.mkdir(parents=True)
    called = []
    monkeypatch.setattr(notices, "tool", lambda *_args: called.append(True))
    with pytest.raises(ValueError, match="output must be a new directory"):
        notices.main(
            [
                "--cargo-about",
                "tool",
                "--cargo",
                "cargo",
                "--fallback-manifest",
                "x",
                "--out",
                str(output),
            ]
        )
    assert called == []
