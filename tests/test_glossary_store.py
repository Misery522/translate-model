from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import glossary_store
from glossary_store import (
    GlossaryConflictError,
    GlossaryDocument,
    GlossaryEntry,
    GlossaryFormatError,
    GlossaryIOError,
    GlossaryStore,
    GlossaryValidationError,
    GlossaryVersionError,
)


def make_entry(**overrides: object) -> GlossaryEntry:
    values: dict[str, object] = {
        "source": "large language model",
        "target": "大语言模型",
        "target_language": "zh-Hans",
        "domain": "technology",
        "case_sensitive": False,
    }
    values.update(overrides)
    return GlossaryEntry(**values)


def test_missing_file_returns_empty_document(tmp_path: Path) -> None:
    document = GlossaryStore(tmp_path / "missing.json").load()

    assert document == GlossaryDocument()
    assert document.entries == []


def test_save_and_load_round_trip_keeps_utf8(tmp_path: Path) -> None:
    path = tmp_path / "data" / "glossary.json"
    store = GlossaryStore(path)
    entry = make_entry(source="人工智能", target="artificial intelligence")

    saved = store.save(GlossaryDocument(entries=[entry]))
    loaded = store.load()

    assert loaded == saved
    raw = path.read_bytes()
    assert "人工智能".encode() in raw
    assert b"\\u4eba" not in raw
    assert json.loads(raw.decode("utf-8"))["version"] == 1


@pytest.mark.parametrize(
    "payload, expected_error",
    [
        ("{not-json", GlossaryFormatError),
        ("[]", GlossaryFormatError),
        ('{"entries": []}', GlossaryVersionError),
        ('{"version": 2, "entries": []}', GlossaryVersionError),
        ('{"version": true, "entries": []}', GlossaryVersionError),
    ],
)
def test_load_reports_corruption_and_version_errors(
    tmp_path: Path,
    payload: str,
    expected_error: type[Exception],
) -> None:
    path = tmp_path / "glossary.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(expected_error):
        GlossaryStore(path).load()


def test_empty_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="不能为空"):
        make_entry(source="  ")

    with pytest.raises(GlossaryValidationError, match="第 1 行"):
        GlossaryStore("unused.json").from_rows(
            [["term", "", "zh-Hans", "technology", False]]
        )


@pytest.mark.parametrize(
    "rows",
    [
        [
            ["API", "接口甲", "zh-Hans", "technology", False],
            ["api", "接口乙", "zh-Hans", "technology", True],
        ],
        [
            ["API", "接口甲", "zh-Hans", "technology", True],
            ["API", "接口乙", "zh-Hans", "technology", True],
        ],
    ],
)
def test_conflicts_in_same_scope_are_rejected(rows: list[list[object]]) -> None:
    with pytest.raises(GlossaryConflictError, match="术语冲突"):
        GlossaryStore("unused.json").from_rows(rows)


def test_case_sensitive_variants_and_different_scopes_are_allowed() -> None:
    rows = [
        ["API", "接口大写", "zh-Hans", "technology", True],
        ["api", "接口小写", "zh-Hans", "technology", True],
        ["API", "接口通用", "zh-Hans", "all", False],
        ["API", "interface", "en", "technology", False],
    ]

    document = GlossaryStore("unused.json").from_rows(rows)

    assert len(document.entries) == 4


def test_load_rejects_conflicts_in_json(tmp_path: Path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    make_entry(source="API").model_dump(),
                    make_entry(source="api", target="应用程序接口").model_dump(),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(GlossaryConflictError):
        GlossaryStore(path).load()


class FakeDataFrame:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.records


def test_row_conversion_supports_arrays_and_dataframe_like_objects(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path / "glossary.json")
    array_rows = [["SDK", "软件开发工具包", "zh-Hans", "technology", "是"]]

    array_document = store.from_rows(array_rows)
    assert array_document.entries[0].case_sensitive is True
    assert store.to_rows(array_document) == [
        ["SDK", "软件开发工具包", "zh-Hans", "technology", True]
    ]

    frame = FakeDataFrame(
        [
            {
                "原词": "cloud",
                "指定译法": "云计算",
                "目标语言": "zh-Hans",
                "领域": "technology",
                "区分大小写": "否",
            }
        ]
    )
    saved_rows = store.save_rows(frame)

    assert saved_rows == [["cloud", "云计算", "zh-Hans", "technology", False]]
    assert store.load_rows() == saved_rows


def test_fully_blank_ui_rows_are_skipped_but_partial_rows_are_rejected() -> None:
    store = GlossaryStore("unused.json")

    document = store.from_rows(
        [
            [None, None, None, None, None],
            ["", "  ", None, float("nan"), ""],
            ["API", "应用程序接口", "zh-Hans", "technology", False],
        ]
    )
    assert [entry.source for entry in document.entries] == ["API"]

    with pytest.raises(GlossaryValidationError, match="第 1 行"):
        store.from_rows([["API", "", "zh-Hans", "technology", False]])


def test_invalid_language_domain_and_row_width_are_explicit() -> None:
    store = GlossaryStore("unused.json")

    with pytest.raises(GlossaryValidationError, match="不支持的目标语言"):
        store.from_rows([["a", "b", "xx", "all", False]])
    with pytest.raises(GlossaryValidationError, match="不支持的领域"):
        store.from_rows([["a", "b", "en", "technical", False]])
    with pytest.raises(GlossaryValidationError, match="应有 5 列"):
        store.from_rows([["a", "b"]])


def test_failed_atomic_replace_preserves_original_and_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "glossary.json"
    store = GlossaryStore(path)
    store.save([make_entry(source="old", target="旧值")])
    original_bytes = path.read_bytes()

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(glossary_store.os, "replace", fail_replace)

    with pytest.raises(GlossaryIOError, match="原子保存"):
        store.save([make_entry(source="new", target="新值")])

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".glossary.json.*.tmp")) == []
