"""本地 JSON 术语库的模型、校验与持久化。

该模块不依赖 Gradio 或 pandas。UI 可直接使用 ``load_rows`` 和
``save_rows``，同时保留结构化的 Pydantic 模型供翻译核心使用。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

TARGET_LANGUAGES: Final[tuple[str, ...]] = (
    "zh-Hans",
    "zh-Hant",
    "en",
    "ja",
    "ko",
    "fr",
    "de",
    "es",
    "ru",
    "pt-BR",
    "ar",
    "it",
)
DOMAINS: Final[tuple[str, ...]] = (
    "all",
    "general",
    "technology",
    "business",
    "finance",
    "legal",
    "medical",
    "academic",
)
TARGET_LANGUAGE_WHITELIST: Final[frozenset[str]] = frozenset(TARGET_LANGUAGES)
DOMAIN_WHITELIST: Final[frozenset[str]] = frozenset(DOMAINS)

# 兼容语义更直观的导入名。
ALLOWED_TARGET_LANGUAGES = TARGET_LANGUAGE_WHITELIST
ALLOWED_DOMAINS = DOMAIN_WHITELIST

GLOSSARY_COLUMNS: Final[tuple[str, ...]] = (
    "source",
    "target",
    "target_language",
    "domain",
    "case_sensitive",
)
GLOSSARY_HEADERS: Final[tuple[str, ...]] = (
    "原词",
    "指定译法",
    "目标语言",
    "领域",
    "区分大小写",
)

_COLUMN_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "source": ("source", "原词", "源词"),
    "target": ("target", "指定译法", "译法"),
    "target_language": ("target_language", "目标语言", "目标语言代码"),
    "domain": ("domain", "领域"),
    "case_sensitive": ("case_sensitive", "区分大小写", "大小写敏感"),
}


class GlossaryError(ValueError):
    """术语库错误基类。"""


class GlossaryFormatError(GlossaryError):
    """JSON 内容或顶层结构无效。"""


class GlossaryValidationError(GlossaryError):
    """术语字段不满足约束。"""


class GlossaryVersionError(GlossaryValidationError):
    """术语库版本缺失或不受支持。"""


class GlossaryConflictError(GlossaryValidationError):
    """同一适用范围存在会同时命中的术语。"""


class GlossaryIOError(GlossaryError):
    """读取或原子写入术语库失败。"""


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}必须是文本")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name}不能为空")
    return value


class GlossaryEntry(BaseModel):
    """一条受目标语言和领域约束的专业术语。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source: str
    target: str
    target_language: str
    domain: str = "all"
    case_sensitive: bool = False

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return _required_text(value, "原词")

    @field_validator("target", mode="before")
    @classmethod
    def validate_target(cls, value: Any) -> str:
        return _required_text(value, "指定译法")

    @field_validator("target_language", mode="before")
    @classmethod
    def validate_target_language(cls, value: Any) -> str:
        value = _required_text(value, "目标语言")
        if value not in TARGET_LANGUAGE_WHITELIST:
            allowed = ", ".join(TARGET_LANGUAGES)
            raise ValueError(f"不支持的目标语言 {value!r}；允许值：{allowed}")
        return value

    @field_validator("domain", mode="before")
    @classmethod
    def validate_domain(cls, value: Any) -> str:
        value = _required_text(value, "领域")
        if value not in DOMAIN_WHITELIST:
            allowed = ", ".join(DOMAINS)
            raise ValueError(f"不支持的领域 {value!r}；允许值：{allowed}")
        return value


class GlossaryDocument(BaseModel):
    """磁盘中的版本化术语库文档。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    version: Literal[1] = 1
    entries: list[GlossaryEntry] = Field(default_factory=list)


def _format_validation_error(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        message = str(item["msg"])
        details.append(f"{location}: {message}" if location else message)
    return "；".join(details)


def _validate_conflicts(entries: Sequence[GlossaryEntry]) -> None:
    """拒绝同一语言、领域中会命中同一输入的两条术语。"""

    scopes: dict[tuple[str, str], list[tuple[int, GlossaryEntry]]] = {}
    for index, entry in enumerate(entries, start=1):
        scope = (entry.target_language, entry.domain)
        for previous_index, previous in scopes.setdefault(scope, []):
            if previous.case_sensitive and entry.case_sensitive:
                conflicts = previous.source == entry.source
            else:
                conflicts = previous.source.casefold() == entry.source.casefold()
            if conflicts:
                raise GlossaryConflictError(
                    "术语冲突：第 "
                    f"{previous_index} 行与第 {index} 行在目标语言 "
                    f"{entry.target_language!r}、领域 {entry.domain!r} 中会同时匹配 "
                    f"{entry.source!r}"
                )
        scopes[scope].append((index, entry))


def _is_missing_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return isinstance(value, str) and not value.strip()


def _coerce_case_sensitive(value: Any, row_number: int) -> bool:
    if _is_missing_cell(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "y", "1", "是"}:
            return True
        if normalized in {"false", "no", "n", "0", "否"}:
            return False
    raise GlossaryValidationError(
        f"第 {row_number} 行的区分大小写值无效；请使用 true/false 或 是/否"
    )


def _mapping_value(record: Mapping[Any, Any], column: str) -> Any:
    for alias in _COLUMN_ALIASES[column]:
        if alias in record:
            return record[alias]
    return None


def _materialize_rows(rows: Any) -> list[Any]:
    """以鸭子类型读取 DataFrame，避免引入 pandas 运行时依赖。"""

    if rows is None:
        return []
    if isinstance(rows, GlossaryDocument):
        return [entry.model_dump() for entry in rows.entries]
    if isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise GlossaryValidationError("术语表必须是二维行数据，不能是文本或单个对象")

    to_dict = getattr(rows, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict(orient="records")
        except TypeError:
            records = to_dict("records")
        if isinstance(records, list):
            return records

    values = getattr(rows, "values", None)
    values_to_list = getattr(values, "tolist", None)
    if callable(values_to_list):
        materialized = values_to_list()
        if isinstance(materialized, list):
            return materialized

    to_list = getattr(rows, "tolist", None)
    if callable(to_list):
        materialized = to_list()
        if isinstance(materialized, list):
            return materialized

    try:
        return list(rows)
    except TypeError as error:
        raise GlossaryValidationError("术语表必须是可迭代的二维行数据") from error


class GlossaryStore:
    """将版本化术语库安全地保存到单个 UTF-8 JSON 文件。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self) -> GlossaryDocument:
        """加载并验证术语库；文件不存在时返回空库。"""

        if not self.path.exists():
            return GlossaryDocument()
        try:
            raw_text = self.path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise GlossaryIOError(f"读取术语库失败：{self.path}：{error}") from error
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise GlossaryFormatError(
                f"术语库 JSON 损坏：第 {error.lineno} 行第 {error.colno} 列：{error.msg}"
            ) from error
        if not isinstance(payload, Mapping):
            raise GlossaryFormatError("术语库 JSON 顶层必须是对象")
        if "version" not in payload:
            raise GlossaryVersionError("术语库缺少 version 字段")
        if isinstance(payload["version"], bool) or payload["version"] != 1:
            raise GlossaryVersionError(
                f"不支持的术语库版本 {payload['version']!r}；当前仅支持版本 1"
            )
        document = self._validate_document(payload)
        _validate_conflicts(document.entries)
        return document

    def save(
        self,
        document: GlossaryDocument
        | Mapping[str, Any]
        | Iterable[GlossaryEntry | Mapping[str, Any]],
    ) -> GlossaryDocument:
        """校验并原子写入术语库，成功后返回规范化文档。"""

        normalized = self._coerce_document(document)
        _validate_conflicts(normalized.entries)
        payload = normalized.model_dump(mode="json")
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        parent = self.path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise GlossaryIOError(f"创建术语库目录失败：{parent}：{error}") from error

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise GlossaryIOError(f"原子保存术语库失败：{self.path}：{error}") from error
        return normalized

    def to_rows(
        self,
        document: GlossaryDocument | Sequence[GlossaryEntry] | None = None,
    ) -> list[list[Any]]:
        """转换为 Gradio Dataframe 可直接显示的二维数组。"""

        if document is None:
            entries = self.load().entries
        elif isinstance(document, GlossaryDocument):
            entries = document.entries
        else:
            entries = list(document)
        return [
            [
                entry.source,
                entry.target,
                entry.target_language,
                entry.domain,
                entry.case_sensitive,
            ]
            for entry in entries
        ]

    def from_rows(self, rows: Any) -> GlossaryDocument:
        """将二维数组或 DataFrame 风格对象转换为已验证文档。"""

        entries: list[GlossaryEntry] = []
        for row_number, raw_row in enumerate(_materialize_rows(rows), start=1):
            if isinstance(raw_row, Mapping):
                values = [_mapping_value(raw_row, column) for column in GLOSSARY_COLUMNS]
            else:
                if isinstance(raw_row, (str, bytes, bytearray)):
                    raise GlossaryValidationError(f"第 {row_number} 行必须是列序列")
                try:
                    values = list(raw_row)
                except TypeError as error:
                    raise GlossaryValidationError(
                        f"第 {row_number} 行必须是列序列"
                    ) from error
                if len(values) != len(GLOSSARY_COLUMNS):
                    raise GlossaryValidationError(
                        f"第 {row_number} 行应有 {len(GLOSSARY_COLUMNS)} 列，"
                        f"实际为 {len(values)} 列"
                    )

            # Gradio 的动态 Dataframe 会保留占位空行；整行为空不代表一条术语。
            if all(_is_missing_cell(value) for value in values):
                continue
            source, target, target_language, domain, case_sensitive = values
            if _is_missing_cell(domain):
                domain = "all"
            case_sensitive = _coerce_case_sensitive(case_sensitive, row_number)
            try:
                entry = GlossaryEntry(
                    source=source,
                    target=target,
                    target_language=target_language,
                    domain=domain,
                    case_sensitive=case_sensitive,
                )
            except ValidationError as error:
                raise GlossaryValidationError(
                    f"第 {row_number} 行无效：{_format_validation_error(error)}"
                ) from error
            entries.append(entry)

        document = GlossaryDocument(entries=entries)
        _validate_conflicts(document.entries)
        return document

    def load_rows(self) -> list[list[Any]]:
        """加载术语库并返回 Gradio Dataframe 行。"""

        return self.to_rows(self.load())

    def save_rows(self, rows: Any) -> list[list[Any]]:
        """转换、校验、保存 UI 行，并返回规范化后的行。"""

        document = self.from_rows(rows)
        saved = self.save(document)
        return self.to_rows(saved)

    @staticmethod
    def _validate_document(payload: Any) -> GlossaryDocument:
        try:
            return GlossaryDocument.model_validate(payload)
        except ValidationError as error:
            raise GlossaryValidationError(
                f"术语库字段校验失败：{_format_validation_error(error)}"
            ) from error

    def _coerce_document(
        self,
        document: GlossaryDocument
        | Mapping[str, Any]
        | Iterable[GlossaryEntry | Mapping[str, Any]],
    ) -> GlossaryDocument:
        if isinstance(document, GlossaryDocument):
            payload: Any = document.model_dump()
        elif isinstance(document, Mapping):
            payload = document
        elif isinstance(document, (str, bytes, bytearray)):
            raise GlossaryValidationError("保存内容必须是术语文档或术语条目集合")
        else:
            try:
                payload = {"version": 1, "entries": list(document)}
            except TypeError as error:
                raise GlossaryValidationError(
                    "保存内容必须是术语文档或术语条目集合"
                ) from error
        return self._validate_document(payload)


__all__ = [
    "ALLOWED_DOMAINS",
    "ALLOWED_TARGET_LANGUAGES",
    "DOMAINS",
    "DOMAIN_WHITELIST",
    "GLOSSARY_COLUMNS",
    "GLOSSARY_HEADERS",
    "GlossaryConflictError",
    "GlossaryDocument",
    "GlossaryEntry",
    "GlossaryError",
    "GlossaryFormatError",
    "GlossaryIOError",
    "GlossaryStore",
    "GlossaryValidationError",
    "GlossaryVersionError",
    "TARGET_LANGUAGES",
    "TARGET_LANGUAGE_WHITELIST",
]
