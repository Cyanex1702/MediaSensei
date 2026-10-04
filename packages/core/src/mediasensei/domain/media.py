from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    UNKNOWN = "unknown"


class MediaDerivativeKind(StrEnum):
    THUMBNAIL = "thumbnail"
    WAVEFORM = "waveform"
    TRANSCODE = "transcode"
    CLIP = "clip"


class VideoFormat(StrEnum):
    MP4 = "mp4"
    WEBM = "webm"


class AudioFormat(StrEnum):
    WAV = "wav"
    FLAC = "flac"
    MP3 = "mp3"
    OGG = "ogg"


@dataclass(frozen=True, slots=True)
class MediaAnalysis:
    sha256: str
    valid: bool
    media_kind: MediaKind
    container: str | None
    duration_seconds: float | None
    bit_rate: int | None
    size_bytes: int | None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    pixel_format: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    tool_revision: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedMedia:
    source_sha256: str
    sha256: str
    object_key: str
    kind: MediaDerivativeKind
    format: str
    mime_type: str
    parameters: dict[str, Any]
    duration_seconds: float | None = None
    tool_revision: str | None = None
