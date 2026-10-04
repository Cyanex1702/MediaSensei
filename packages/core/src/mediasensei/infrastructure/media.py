from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mediasensei.domain.jobs import ProcessorSpec, ResourceHints, ResourceLevel, WorkItem
from mediasensei.domain.media import (
    AudioFormat,
    DerivedMedia,
    MediaAnalysis,
    MediaDerivativeKind,
    MediaKind,
    VideoFormat,
)
from mediasensei.infrastructure.storage import ContentAddressedStore

if TYPE_CHECKING:
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.worker import ProcessorRegistry

CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


class FFmpegUnavailableError(RuntimeError):
    pass


class FFmpegExecutionError(RuntimeError):
    pass


class FFmpegToolchain:
    """Bounded, shell-free ffprobe/ffmpeg adapter with explicit binary provenance."""

    def __init__(
        self,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        timeout_seconds: int = 300,
        runner: CommandRunner | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg or os.environ.get("MEDIASENSEI_FFMPEG") or shutil.which("ffmpeg")
        self.ffprobe = ffprobe or os.environ.get("MEDIASENSEI_FFPROBE") or shutil.which("ffprobe")
        self.timeout_seconds = max(5, min(timeout_seconds, 3600))
        self.runner = runner or _subprocess_runner
        self.version = self._version()

    def available(self) -> bool:
        return self.ffmpeg is not None and self.ffprobe is not None

    def probe(self, path: str | Path) -> dict[str, Any]:
        self._require_available()
        source = Path(path).resolve(strict=True)
        completed = self._run(
            [
                str(self.ffprobe),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(source),
            ]
        )
        if len(completed.stdout) > 8 * 1024 * 1024:
            raise FFmpegExecutionError("ffprobe metadata exceeded the 8 MiB safety limit")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise FFmpegExecutionError("ffprobe returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise FFmpegExecutionError("ffprobe returned an invalid metadata object")
        return payload

    def validate_decode(self, path: str | Path) -> None:
        self._require_available()
        source = Path(path).resolve(strict=True)
        self._run(
            [
                str(self.ffmpeg),
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0",
                "-f",
                "null",
                os.devnull,
            ],
            timeout=max(self.timeout_seconds, 900),
        )

    def thumbnail(
        self,
        path: str | Path,
        destination: Path,
        *,
        timestamp_seconds: float,
        width: int,
    ) -> None:
        self._require_available()
        source = Path(path).resolve(strict=True)
        bounded_time = max(0.0, min(float(timestamp_seconds), 86400.0))
        bounded_width = max(64, min(int(width), 4096))
        self._run(
            [
                str(self.ffmpeg),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{bounded_time:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                f"scale={bounded_width}:-2:force_original_aspect_ratio=decrease",
                "-an",
                "-map_metadata",
                "-1",
                "-threads",
                "1",
                "-y",
                str(destination),
            ]
        )

    def waveform(
        self,
        path: str | Path,
        destination: Path,
        *,
        width: int,
        height: int,
        color: str,
    ) -> None:
        self._require_available()
        source = Path(path).resolve(strict=True)
        bounded_width = max(320, min(int(width), 4096))
        bounded_height = max(80, min(int(height), 1024))
        safe_color = color if color in {"66efc0", "ffffff", "f4b860", "4cc9f0"} else "66efc0"
        self._run(
            [
                str(self.ffmpeg),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-filter_complex",
                f"aformat=channel_layouts=mono,showwavespic=s={bounded_width}x{bounded_height}:colors=0x{safe_color}",
                "-frames:v",
                "1",
                "-map_metadata",
                "-1",
                "-threads",
                "1",
                "-y",
                str(destination),
            ]
        )

    def transcode(
        self,
        path: str | Path,
        destination: Path,
        *,
        media_kind: MediaKind,
        output_format: str,
        start_seconds: float | None = None,
        duration_seconds: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        self._require_available()
        source = Path(path).resolve(strict=True)
        command = [
            str(self.ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
        ]
        if start_seconds is not None:
            command.extend(["-ss", f"{_bounded_seconds(start_seconds):.3f}"])
        if duration_seconds is not None:
            duration = _bounded_seconds(duration_seconds)
            if duration <= 0:
                raise ValueError("Clip duration must be greater than zero")
            command.extend(["-t", f"{duration:.3f}"])
        if media_kind == MediaKind.VIDEO:
            video_format = VideoFormat(output_format)
            command.extend(["-map", "0:v:0", "-map", "0:a?"])
            if width is not None or height is not None:
                target_width = max(64, min(int(width or -2), 7680)) if width is not None else -2
                target_height = max(64, min(int(height or -2), 4320)) if height is not None else -2
                command.extend(
                    [
                        "-vf",
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                    ]
                )
            if video_format == VideoFormat.MP4:
                command.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-crf",
                        "23",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "160k",
                        "-movflags",
                        "+faststart",
                    ]
                )
            else:
                command.extend(
                    [
                        "-c:v",
                        "libvpx-vp9",
                        "-crf",
                        "32",
                        "-b:v",
                        "0",
                        "-c:a",
                        "libopus",
                        "-b:a",
                        "128k",
                    ]
                )
        elif media_kind == MediaKind.AUDIO:
            audio_format = AudioFormat(output_format)
            codecs = {
                AudioFormat.WAV: ["-c:a", "pcm_s16le"],
                AudioFormat.FLAC: ["-c:a", "flac"],
                AudioFormat.MP3: ["-c:a", "libmp3lame", "-q:a", "2"],
                AudioFormat.OGG: ["-c:a", "libopus", "-b:a", "128k"],
            }
            command.extend(["-map", "0:a:0", "-vn", *codecs[audio_format]])
        else:
            raise ValueError("Media kind must be video or audio for transcoding")
        command.extend(
            [
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-threads",
                "1",
                "-y",
                str(destination),
            ]
        )
        self._run(command, timeout=max(self.timeout_seconds, 1800))

    def _run(
        self, command: list[str], *, timeout: int | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self.runner(command, timeout or self.timeout_seconds)
        except (OSError, subprocess.SubprocessError) as error:
            raise FFmpegExecutionError(str(error)[:1000]) from error
        if completed.returncode != 0:
            detail = (completed.stderr or "FFmpeg returned a non-zero exit code").strip()
            raise FFmpegExecutionError(detail[:1000])
        return completed

    def _require_available(self) -> None:
        if not self.available():
            raise FFmpegUnavailableError(
                "FFmpeg and ffprobe are required but were not found on PATH; install FFmpeg and retry the failed items"
            )

    def _version(self) -> str | None:
        if self.ffmpeg is None:
            return None
        try:
            completed = self.runner([self.ffmpeg, "-version"], 5)
        except (OSError, subprocess.SubprocessError):
            return None
        first = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        return first or None


class MediaPipeline:
    """Content-safe media inspection and immutable FFmpeg derivatives."""

    def __init__(
        self,
        store: ContentAddressedStore,
        *,
        toolchain: FFmpegToolchain | None = None,
    ) -> None:
        self.store = store
        self.toolchain = toolchain or FFmpegToolchain()

    def inspect(
        self,
        path: str | Path,
        *,
        sha256: str | None = None,
        validate_decode: bool = False,
    ) -> MediaAnalysis:
        source = Path(path).resolve(strict=True)
        digest = sha256 or _sha256(source)
        try:
            payload = self.toolchain.probe(source)
            analysis = _analysis_from_probe(
                digest,
                payload,
                tool_revision=self.toolchain.version,
                fallback_size=source.stat().st_size,
            )
            if validate_decode:
                self.toolchain.validate_decode(source)
            return analysis
        except (FFmpegExecutionError, FFmpegUnavailableError, OSError, ValueError) as error:
            return MediaAnalysis(
                sha256=digest,
                valid=False,
                media_kind=MediaKind.UNKNOWN,
                container=None,
                duration_seconds=None,
                bit_rate=None,
                size_bytes=source.stat().st_size,
                tool_revision=self.toolchain.version,
                error=str(error)[:1000],
            )

    def thumbnail(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        timestamp_seconds: float = 1.0,
        width: int = 960,
    ) -> DerivedMedia:
        parameters = {"timestamp_seconds": timestamp_seconds, "width": width}
        return self._derive(
            path,
            source_sha256=source_sha256,
            kind=MediaDerivativeKind.THUMBNAIL,
            output_format="png",
            mime_type="image/png",
            parameters=parameters,
            producer=lambda target: self.toolchain.thumbnail(
                path,
                target,
                timestamp_seconds=timestamp_seconds,
                width=width,
            ),
        )

    def waveform(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        width: int = 1200,
        height: int = 240,
        color: str = "66efc0",
    ) -> DerivedMedia:
        parameters = {"width": width, "height": height, "color": color}
        return self._derive(
            path,
            source_sha256=source_sha256,
            kind=MediaDerivativeKind.WAVEFORM,
            output_format="png",
            mime_type="image/png",
            parameters=parameters,
            producer=lambda target: self.toolchain.waveform(
                path,
                target,
                width=width,
                height=height,
                color=color,
            ),
        )

    def transcode(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        media_kind: MediaKind,
        output_format: str,
        start_seconds: float | None = None,
        duration_seconds: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> DerivedMedia:
        normalized_format = output_format.lower()
        if media_kind == MediaKind.VIDEO:
            VideoFormat(normalized_format)
        elif media_kind == MediaKind.AUDIO:
            AudioFormat(normalized_format)
        else:
            raise ValueError("Media kind must be video or audio")
        parameters = {
            "media_kind": media_kind.value,
            "format": normalized_format,
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
            "width": width,
            "height": height,
        }
        kind = (
            MediaDerivativeKind.CLIP
            if start_seconds is not None or duration_seconds is not None
            else MediaDerivativeKind.TRANSCODE
        )
        return self._derive(
            path,
            source_sha256=source_sha256,
            kind=kind,
            output_format=normalized_format,
            mime_type=_mime_type(media_kind, normalized_format),
            parameters=parameters,
            duration_seconds=duration_seconds,
            producer=lambda target: self.toolchain.transcode(
                path,
                target,
                media_kind=media_kind,
                output_format=normalized_format,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                width=width,
                height=height,
            ),
        )

    def _derive(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        kind: MediaDerivativeKind,
        output_format: str,
        mime_type: str,
        parameters: dict[str, Any],
        producer: Callable[[Path], None],
        duration_seconds: float | None = None,
    ) -> DerivedMedia:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"media-{kind.value}-",
            suffix=f".{output_format}",
            dir=self.store.temp_root,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        temporary.unlink(missing_ok=True)
        try:
            producer(temporary)
            if not temporary.is_file() or temporary.stat().st_size < 1:
                raise FFmpegExecutionError("FFmpeg did not create the expected derivative")
            stored = self.store.import_file(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return DerivedMedia(
            source_sha256=source_sha256,
            sha256=stored.sha256,
            object_key=stored.object_key,
            kind=kind,
            format=output_format,
            mime_type=mime_type,
            parameters=parameters,
            duration_seconds=duration_seconds,
            tool_revision=self.toolchain.version,
        )


def register_media_processors(
    registry: ProcessorRegistry,
    catalog: Catalog,
    *,
    toolchain: FFmpegToolchain | None = None,
) -> None:
    store = ContentAddressedStore(catalog.workspace)
    pipeline = MediaPipeline(store, toolchain=toolchain)

    def inspect_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        source = store.resolve(item.input_ref)
        analysis = pipeline.inspect(
            source,
            sha256=item.input_hash,
            validate_decode=bool(parameters.get("validate_decode", False)),
        )
        catalog.upsert_media_analysis(analysis)
        output: dict[str, Any] = {"analysis": asdict(analysis)}
        if not analysis.valid:
            raise FFmpegExecutionError(analysis.error or "Media inspection failed")
        if bool(parameters.get("preview", True)):
            if analysis.media_kind == MediaKind.VIDEO:
                preview = pipeline.thumbnail(
                    source,
                    source_sha256=item.input_hash,
                    timestamp_seconds=float(parameters.get("timestamp_seconds", 1.0)),
                    width=int(parameters.get("preview_width", 960)),
                )
            else:
                preview = pipeline.waveform(
                    source,
                    source_sha256=item.input_hash,
                    width=int(parameters.get("waveform_width", 1200)),
                    height=int(parameters.get("waveform_height", 240)),
                )
            catalog.record_derived_media(preview)
            output["preview"] = asdict(preview)
        return output

    def derive_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        source = store.resolve(item.input_ref)
        kind = MediaDerivativeKind(str(parameters.get("kind", "transcode")))
        if kind == MediaDerivativeKind.THUMBNAIL:
            derived = pipeline.thumbnail(
                source,
                source_sha256=item.input_hash,
                timestamp_seconds=float(parameters.get("timestamp_seconds", 1.0)),
                width=int(parameters.get("width", 960)),
            )
        elif kind == MediaDerivativeKind.WAVEFORM:
            derived = pipeline.waveform(
                source,
                source_sha256=item.input_hash,
                width=int(parameters.get("width", 1200)),
                height=int(parameters.get("height", 240)),
                color=str(parameters.get("color", "66efc0")),
            )
        else:
            derived = pipeline.transcode(
                source,
                source_sha256=item.input_hash,
                media_kind=MediaKind(str(parameters["media_kind"])),
                output_format=str(parameters["format"]),
                start_seconds=(
                    float(parameters["start_seconds"])
                    if parameters.get("start_seconds") is not None
                    else None
                ),
                duration_seconds=(
                    float(parameters["duration_seconds"])
                    if parameters.get("duration_seconds") is not None
                    else None
                ),
                width=int(parameters["width"]) if parameters.get("width") is not None else None,
                height=(
                    int(parameters["height"]) if parameters.get("height") is not None else None
                ),
            )
        catalog.record_derived_media(derived)
        return {"derived": asdict(derived)}

    registry.register("media.inspect", inspect_processor)
    registry.register("media.derive", derive_processor)


def media_processor_spec(
    processor_id: str = "media.inspect",
    *,
    toolchain: FFmpegToolchain | None = None,
) -> ProcessorSpec:
    tools = toolchain or FFmpegToolchain()
    return ProcessorSpec(
        id=processor_id,
        version="1.0.0",
        deterministic=True,
        cacheable=tools.version is not None,
        model_revision=tools.version or "ffmpeg-unavailable",
        resource_hints=ResourceHints(
            cpu=ResourceLevel.HIGH,
            memory=ResourceLevel.MEDIUM,
            disk=ResourceLevel.HIGH,
        ),
    )


def _analysis_from_probe(
    sha256: str,
    payload: dict[str, Any],
    *,
    tool_revision: str | None,
    fallback_size: int,
) -> MediaAnalysis:
    raw_format = payload.get("format")
    format_data: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    raw_streams = payload.get("streams")
    streams: list[Any] = raw_streams if isinstance(raw_streams, list) else []
    video: dict[str, Any] | None = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    audio: dict[str, Any] | None = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )
    if video is None and audio is None:
        raise ValueError("The file contains no supported video or audio streams")
    media_kind = MediaKind.VIDEO if video is not None else MediaKind.AUDIO
    duration = _float_value(format_data.get("duration"))
    if duration is None:
        selected = video or audio or {}
        duration = _float_value(selected.get("duration"))
    tags_value = format_data.get("tags")
    tags = (
        {
            str(key)[:80]: str(value)[:500]
            for key, value in tags_value.items()
            if isinstance(key, str) and isinstance(value, (str, int, float))
        }
        if isinstance(tags_value, dict)
        else {}
    )
    return MediaAnalysis(
        sha256=sha256,
        valid=True,
        media_kind=media_kind,
        container=_container(format_data.get("format_name")),
        duration_seconds=round(duration, 6) if duration is not None else None,
        bit_rate=_int_value(format_data.get("bit_rate")),
        size_bytes=_int_value(format_data.get("size")) or fallback_size,
        video_codec=str(video.get("codec_name")) if video and video.get("codec_name") else None,
        width=_int_value(video.get("width")) if video else None,
        height=_int_value(video.get("height")) if video else None,
        fps=_frame_rate(video.get("avg_frame_rate")) if video else None,
        pixel_format=str(video.get("pix_fmt")) if video and video.get("pix_fmt") else None,
        audio_codec=str(audio.get("codec_name")) if audio and audio.get("codec_name") else None,
        sample_rate=_int_value(audio.get("sample_rate")) if audio else None,
        channels=_int_value(audio.get("channels")) if audio else None,
        channel_layout=(
            str(audio.get("channel_layout")) if audio and audio.get("channel_layout") else None
        ),
        tags=tags,
        tool_revision=tool_revision,
    )


def _subprocess_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _frame_rate(value: Any) -> float | None:
    if not isinstance(value, str) or not value or value in {"0/0", "N/A"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        result = float(numerator) / float(denominator)
        return round(result, 6) if result > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _float_value(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    try:
        result = int(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _container(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.split(",", 1)[0]


def _bounded_seconds(value: float) -> float:
    return max(0.0, min(float(value), 86400.0))


def _mime_type(media_kind: MediaKind, output_format: str) -> str:
    if media_kind == MediaKind.VIDEO:
        return {"mp4": "video/mp4", "webm": "video/webm"}[output_format]
    return {
        "wav": "audio/wav",
        "flac": "audio/flac",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
    }[output_format]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
