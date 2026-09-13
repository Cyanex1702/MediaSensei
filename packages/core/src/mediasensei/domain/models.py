from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    TABULAR = "tabular"
    UNKNOWN = "unknown"


class AssetState(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class Project:
    name: str
    id: UUID = field(default_factory=uuid4)
    description: str = ""
    data_policy: str = "local_only"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Asset:
    project_id: UUID
    sha256: str
    original_filename: str
    media_type: MediaType
    object_key: str
    byte_size: int
    id: UUID = field(default_factory=uuid4)
    state: AssetState = AssetState.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    project_id: UUID
    version: int
    manifest_hash: str
    sample_count: int
    split_seed: int = 42
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
