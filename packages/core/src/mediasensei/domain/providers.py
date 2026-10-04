from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any


class DatasetProviderKind(StrEnum):
    HUGGING_FACE = "huggingface"
    KAGGLE = "kaggle"


class ProviderImportState(StrEnum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    IMPORTING = "importing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderFileState(StrEnum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ProviderFile:
    path: str
    byte_size: int | None = None
    sha256: str | None = None
    etag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_path = self.path.replace("\\", "/").strip()
        path = PurePosixPath(raw_path)
        parts = raw_path.split("/")
        if (
            not raw_path
            or path.is_absolute()
            or any(part in {"", ".", ".."} or ":" in part for part in parts)
        ):
            raise ValueError("Provider file paths must be safe relative POSIX paths")
        normalized = path.as_posix()
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("Provider file sizes cannot be negative")
        if self.sha256 is not None and (
            len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256.lower())
        ):
            raise ValueError("Provider file SHA-256 values must contain 64 hexadecimal characters")
        object.__setattr__(self, "path", normalized)
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", self.sha256.lower())


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    provider_id: str
    provider_version: str
    dataset_id: str
    requested_revision: str | None
    resolved_revision: str
    source_uri: str
    files: tuple[ProviderFile, ...]
    title: str | None = None
    license: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.provider_version.strip():
            raise ValueError("Dataset snapshots require provider identity and version")
        if not self.dataset_id.strip() or not self.resolved_revision.strip():
            raise ValueError("Dataset snapshots require dataset and resolved revision identities")
        if not self.files:
            raise ValueError("Dataset snapshots must contain at least one file")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Dataset snapshots cannot contain duplicate file paths")


@dataclass(frozen=True, slots=True)
class ProviderImportOptions:
    allow_patterns: tuple[str, ...] = ()
    ignore_patterns: tuple[str, ...] = ()
    max_files: int = 10_000
    max_file_bytes: int = 2 * 1024**3
    max_total_bytes: int = 20 * 1024**3

    def __post_init__(self) -> None:
        if not 1 <= self.max_files <= 100_000:
            raise ValueError("max_files must be between 1 and 100000")
        if not 1 <= self.max_file_bytes <= 100 * 1024**3:
            raise ValueError("max_file_bytes must be between 1 byte and 100 GiB")
        if not 1 <= self.max_total_bytes <= 1024 * 1024**3:
            raise ValueError("max_total_bytes must be between 1 byte and 1 TiB")


@dataclass(frozen=True, slots=True)
class ProviderImportResult:
    import_id: str
    provider_id: str
    dataset_id: str
    resolved_revision: str
    imported_files: int
    skipped_files: int
    failed_files: int
    imported_bytes: int
    manifest_hash: str
