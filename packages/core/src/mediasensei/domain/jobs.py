from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CACHED = "cached"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RuntimeProfile(StrEnum):
    ECO = "eco"
    BALANCED = "balanced"
    MAXIMUM = "maximum"
    CUSTOM = "custom"


class ResourceLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass(frozen=True, slots=True)
class ResourceHints:
    cpu: ResourceLevel = ResourceLevel.LOW
    memory: ResourceLevel = ResourceLevel.LOW
    disk: ResourceLevel = ResourceLevel.LOW
    network: ResourceLevel = ResourceLevel.NONE
    gpu: ResourceLevel = ResourceLevel.NONE
    vram: ResourceLevel = ResourceLevel.NONE


@dataclass(frozen=True, slots=True)
class ProcessorSpec:
    id: str
    version: str
    deterministic: bool = True
    cacheable: bool = True
    model_revision: str | None = None
    resource_hints: ResourceHints = field(default_factory=ResourceHints)

    def cache_key(self, input_hash: str, parameters: dict[str, Any]) -> str:
        payload = {
            "input_hash": input_hash,
            "processor_id": self.id,
            "processor_version": self.version,
            "parameters": parameters,
            "model_revision": self.model_revision,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkItem:
    input_hash: str
    input_ref: str
    position: int
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    id: str
    project_id: str
    kind: str
    state: JobState
    profile: RuntimeProfile
    processor: ProcessorSpec
    parameters: dict[str, Any]
    total_items: int
    processed_count: int
    failed_count: int
    skipped_count: int
    cached_count: int
    progress: int
    checkpoint: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @property
    def terminal(self) -> bool:
        return self.state in {
            JobState.COMPLETED,
            JobState.COMPLETED_WITH_ERRORS,
            JobState.FAILED,
            JobState.CANCELLED,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)
