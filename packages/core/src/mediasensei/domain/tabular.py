from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TabularFormat(StrEnum):
    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    JSON = "json"
    JSONL = "jsonl"
    PARQUET = "parquet"
    SQLITE = "sqlite"
    DUCKDB = "duckdb"

    @classmethod
    def from_filename(cls, filename: str) -> TabularFormat:
        suffix = filename.lower().rsplit(".", 1)[-1]
        aliases = {"ndjson": cls.JSONL, "db": cls.SQLITE, "sqlite3": cls.SQLITE}
        try:
            return aliases[suffix] if suffix in aliases else cls(suffix)
        except ValueError as error:
            raise ValueError(f"Unsupported tabular format: .{suffix}") from error


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    CONTAINS = "contains"
    IN = "in"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


@dataclass(frozen=True, slots=True)
class TabularFilter:
    column: str
    operator: FilterOperator
    value: Any = None


@dataclass(frozen=True, slots=True)
class TabularQuery:
    filters: tuple[TabularFilter, ...] = ()
    search: str | None = None
    sort_by: str | None = None
    descending: bool = False
    visible_columns: tuple[str, ...] = ()
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    name: str
    arrow_type: str
    null_count: int
    distinct_count: int
    minimum: Any = None
    maximum: Any = None
    mean: float | None = None
    frequencies: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TabularProfile:
    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]
    sample: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TabularAnalysis:
    analysis_key: str
    source_sha256: str
    source_format: TabularFormat
    normalized_sha256: str
    normalized_object_key: str
    profile: TabularProfile
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TabularExportResult:
    format: TabularFormat
    path: str
    sha256: str
    row_count: int
    column_count: int
