from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import ceil
from typing import Any


class AcquisitionModality(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    TABULAR = "tabular"


class TargetUnit(StrEnum):
    ACCEPTED_ASSETS = "accepted_assets"
    CLIPS = "clips"
    TOTAL_DURATION_SECONDS = "total_duration_seconds"
    DOCUMENTS = "documents"
    TOKENS = "tokens"
    ROWS = "rows"


class AcquisitionRunState(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    READY = "ready"
    DISCOVERING = "discovering"
    ACQUIRING = "acquiring"
    VALIDATING = "validating"
    REPLENISHING = "replenishing"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_SHORTFALL = "completed_with_shortfall"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CandidateState(StrEnum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVIEW = "review"
    FAILED = "failed"


class AcquisitionDecisionKind(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVIEW = "review"


class AcquisitionReason(StrEnum):
    ACCEPTED = "accepted"
    LOW_RESOLUTION = "low_resolution"
    CORRUPT = "corrupt"
    UNSUPPORTED_FORMAT = "unsupported_format"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NEAR = "duplicate_near"
    TEXT_HEAVY = "text_heavy"
    LOW_QUALITY = "low_quality"
    IRRELEVANT = "irrelevant"
    LICENSE_NOT_ALLOWED = "license_not_allowed"
    SOURCE_LIMIT_REACHED = "source_limit_reached"
    DOWNLOAD_FAILED = "download_failed"
    POLICY_BLOCKED = "policy_blocked"
    USER_ACCEPTED = "user_accepted"
    USER_REJECTED = "user_rejected"
    NEEDS_REVIEW = "needs_review"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class TargetSpec:
    unit: TargetUnit = TargetUnit.ACCEPTED_ASSETS
    count: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.count <= 1_000_000_000:
            raise ValueError("Target count must be between 1 and 1000000000")


@dataclass(frozen=True, slots=True)
class AcquisitionBudget:
    max_candidates: int = 1_500
    max_download_bytes: int = 25 * 1024**3
    max_storage_bytes: int = 20 * 1024**3
    max_requests: int = 2_000
    max_external_cost: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_candidates <= 1_000_000:
            raise ValueError("max_candidates must be between 1 and 1000000")
        if self.max_download_bytes < 1 or self.max_storage_bytes < 1:
            raise ValueError("Acquisition byte budgets must be positive")
        if not 1 <= self.max_requests <= 1_000_000:
            raise ValueError("max_requests must be between 1 and 1000000")
        if self.max_external_cost is not None and self.max_external_cost < 0:
            raise ValueError("External cost budget cannot be negative")


@dataclass(frozen=True, slots=True)
class AcquisitionSpec:
    modality: AcquisitionModality
    topic: str
    target: TargetSpec = field(default_factory=TargetSpec)
    categories: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    provider_ids: tuple[str, ...] = ("wikimedia-commons",)
    min_width: int = 512
    min_height: int = 512
    min_quality: float = 15.0
    reject_corrupt: bool = True
    reject_exact_duplicates: bool = True
    reject_near_duplicates: bool = True
    reject_text_heavy: bool = False
    relevance_strategy: str = "auto"
    replenish_until_target: bool = True
    near_duplicate_threshold: int = 8
    budget: AcquisitionBudget = field(default_factory=AcquisitionBudget)
    allowed_licenses: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        clean_topic = " ".join(self.topic.split())
        if not clean_topic or len(clean_topic) > 500:
            raise ValueError("Acquisition topic must contain 1 to 500 characters")
        if (
            self.modality is AcquisitionModality.IMAGE
            and self.target.unit is not TargetUnit.ACCEPTED_ASSETS
        ):
            raise ValueError("Image acquisition currently targets accepted assets")
        if not 1 <= self.min_width <= 100_000 or not 1 <= self.min_height <= 100_000:
            raise ValueError("Image dimensions must be between 1 and 100000")
        if not 0 <= self.min_quality <= 100:
            raise ValueError("Minimum quality must be between 0 and 100")
        if not 0 <= self.near_duplicate_threshold <= 64:
            raise ValueError("Near-duplicate threshold must be between 0 and 64")
        if self.relevance_strategy not in {"auto", "metadata", "manual", "disabled"}:
            raise ValueError("Unsupported relevance strategy")
        if not self.provider_ids:
            raise ValueError("At least one discovery provider is required")
        object.__setattr__(self, "allowed_licenses", tuple(v.strip().casefold() for v in self.allowed_licenses if v.strip()))
        object.__setattr__(self, "allowed_domains", tuple(v.strip().casefold() for v in self.allowed_domains if v.strip()))
        object.__setattr__(self, "topic", clean_topic)
        object.__setattr__(self, "categories", _clean_values(self.categories, 50))
        object.__setattr__(self, "queries", _clean_values(self.queries, 100))
        object.__setattr__(self, "provider_ids", _clean_values(self.provider_ids, 20))


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    query: str
    modality: AcquisitionModality = AcquisitionModality.IMAGE
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    provider_id: str
    remote_id: str
    source_url: str
    landing_page_url: str | None = None
    preview_url: str | None = None
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    author: str | None = None
    license: str | None = None
    estimated_size: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.remote_id.strip():
            raise ValueError("Discovery candidates require provider and remote identities")
        if not self.source_url.strip():
            raise ValueError("Discovery candidates require a source URL")


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    candidates: tuple[DiscoveryCandidate, ...]
    next_cursor: str | None = None
    provider_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class AcquisitionDecision:
    decision: AcquisitionDecisionKind
    reason: AcquisitionReason
    evaluator_id: str
    evaluator_version: str
    scores: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class YieldSnapshot:
    target: int
    discovered: int
    downloaded: int
    evaluated: int
    accepted: int
    rejected: int
    review: int
    failed: int

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.accepted)

    @property
    def observed_yield(self) -> float:
        return self.accepted / self.evaluated if self.evaluated else 0.0

    def estimated_additional(self, *, prior_yield: float = 0.65, margin: float = 1.15) -> int:
        rate = self.observed_yield if self.evaluated >= 5 else prior_yield
        return ceil(self.remaining / max(0.05, rate) * margin) if self.remaining else 0


def _clean_values(values: tuple[str, ...], limit: int) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(" ".join(value.split()) for value in values if value.strip()))
    if len(cleaned) > limit or any(len(value) > 500 for value in cleaned):
        raise ValueError("Acquisition lists exceed their configured limits")
    return cleaned
