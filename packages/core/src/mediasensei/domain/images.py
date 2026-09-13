from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class FitMode(StrEnum):
    CONTAIN = "contain"
    COVER = "cover"
    PAD = "pad"
    STRETCH = "stretch"


class SplitStrategy(StrEnum):
    RANDOM = "random"
    STRATIFIED = "stratified"
    GROUP_AWARE = "group_aware"
    SOURCE_AWARE = "source_aware"
    MANUAL = "manual"


class OCRAction(StrEnum):
    DETECT_ONLY = "detect_only"
    FILTER = "filter"
    QUARANTINE = "quarantine"
    STORE_TEXT = "store_text"


@dataclass(frozen=True, slots=True)
class ImageAnalysis:
    sha256: str
    valid: bool
    format: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    color_mode: str | None
    exif_orientation: int | None
    has_alpha: bool
    perceptual_hash: str | None
    blur_score: float | None
    quality_score: float | None
    error: str | None = None
    ocr: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DerivedImage:
    source_sha256: str
    sha256: str
    object_key: str
    kind: str
    format: str
    width: int
    height: int
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DatasetSample:
    asset_id: str
    sha256: str
    object_key: str
    filename: str
    label: str = "unlabeled"
    source_key: str | None = None
    group_key: str | None = None
    perceptual_hash: str | None = None
    split: str | None = None

    def assigned(self, split: str) -> DatasetSample:
        return replace(self, split=split)


@dataclass(frozen=True, slots=True)
class LeakageIssue:
    left_asset_id: str
    right_asset_id: str
    left_split: str
    right_split: str
    kind: str
    distance: int


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: str
    manifest_hash: str
    sample_count: int
    split_counts: dict[str, int]
