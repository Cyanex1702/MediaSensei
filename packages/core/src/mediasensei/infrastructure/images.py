from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from statistics import fmean, median
from typing import TYPE_CHECKING, Any, cast

from mediasensei_plugin_sdk import OCRProvider, OCRRegion, OCRResult  # type: ignore[import-untyped]

from mediasensei.domain.images import DerivedImage, FitMode, ImageAnalysis, OCRAction
from mediasensei.infrastructure.storage import ContentAddressedStore

if TYPE_CHECKING:
    from mediasensei.domain.jobs import WorkItem
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.worker import ProcessorRegistry

try:
    from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError
except ImportError as error:  # pragma: no cover - exercised by installation checks
    raise RuntimeError(
        "Image support requires the 'image' extra: pip install mediasensei[image]"
    ) from error

_RESAMPLING = Image.Resampling.LANCZOS
_SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(ValueError):
    pass


class OCRUnavailableError(RuntimeError):
    pass


class TesseractOCRProvider:
    provider_id = "tesseract"

    def __init__(self, executable: str | None = None, *, timeout_seconds: int = 60) -> None:
        self.executable = executable or os.environ.get("MEDIASENSEI_TESSERACT") or shutil.which("tesseract")
        self.timeout_seconds = max(1, timeout_seconds)
        self.version = self._version()

    def available(self) -> bool:
        return self.executable is not None

    def recognize(self, image_path: Path, *, language: str | None = None) -> OCRResult:
        if self.executable is None:
            raise OCRUnavailableError(
                "Tesseract is not installed or is not available on PATH; install it and retry the failed items"
            )
        command = [self.executable, str(image_path), "stdout"]
        if language:
            command.extend(["-l", language])
        command.extend(["tsv", "--psm", "6"])
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "Tesseract returned a non-zero exit code"
            raise RuntimeError(detail[:1000])

        rows = csv.DictReader(io.StringIO(completed.stdout), delimiter="\t")
        regions: list[OCRRegion] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            confidence_value = float(row.get("conf") or -1)
            confidence = confidence_value / 100 if confidence_value >= 0 else None
            bounds = (
                int(row.get("left") or 0),
                int(row.get("top") or 0),
                int(row.get("width") or 0),
                int(row.get("height") or 0),
            )
            regions.append(OCRRegion(text=text, confidence=confidence, bounds=bounds))
        confidences = [region.confidence for region in regions if region.confidence is not None]
        return OCRResult(
            text=" ".join(region.text for region in regions),
            confidence=fmean(confidences) if confidences else None,
            regions=tuple(regions),
            language=language,
            provider=self.provider_id,
            provider_version=self.version,
        )

    def _version(self) -> str | None:
        if self.executable is None:
            return None
        try:
            completed = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
        return first_line.strip() or None


class ImagePipeline:
    """Content-safe image inspection and derivative generation."""

    def __init__(self, store: ContentAddressedStore) -> None:
        self.store = store

    def inspect(
        self,
        path: str | Path,
        *,
        sha256: str | None = None,
        ocr_provider: OCRProvider | None = None,
        ocr_language: str | None = None,
    ) -> ImageAnalysis:
        image_path = Path(path).resolve(strict=True)
        digest = sha256 or _sha256(image_path)
        try:
            with Image.open(image_path) as candidate:
                candidate.verify()
            with Image.open(image_path) as source:
                source.load()
                original_format = (source.format or "").upper() or None
                mime_type = Image.MIME.get(original_format or "")
                orientation_value = source.getexif().get(274)
                orientation = int(orientation_value) if orientation_value is not None else None
                normalized = ImageOps.exif_transpose(source)
                width, height = normalized.size
                if width < 1 or height < 1:
                    raise ImageValidationError("Image dimensions must be positive")
                phash = perceptual_hash(normalized)
                blur = blur_score(normalized)
                quality = round(min(100.0, 25.0 * math.log10(1.0 + blur)), 2)
                has_alpha = normalized.mode in {"RGBA", "LA"} or (
                    normalized.mode == "P" and "transparency" in normalized.info
                )
                ocr_payload = None
                if ocr_provider is not None:
                    if not ocr_provider.available():
                        raise OCRUnavailableError(
                            f"OCR provider '{ocr_provider.provider_id}' is unavailable"
                        )
                    ocr_payload = _ocr_dict(
                        ocr_provider.recognize(image_path, language=ocr_language)
                    )
                return ImageAnalysis(
                    sha256=digest,
                    valid=True,
                    format=original_format,
                    mime_type=mime_type,
                    width=width,
                    height=height,
                    color_mode=normalized.mode,
                    exif_orientation=orientation,
                    has_alpha=has_alpha,
                    perceptual_hash=phash,
                    blur_score=round(blur, 4),
                    quality_score=quality,
                    ocr=ocr_payload,
                )
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
            return ImageAnalysis(
                sha256=digest,
                valid=False,
                format=None,
                mime_type=None,
                width=None,
                height=None,
                color_mode=None,
                exif_orientation=None,
                has_alpha=False,
                perceptual_hash=None,
                blur_score=None,
                quality_score=None,
                error=str(error)[:1000],
            )

    def thumbnail(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        max_size: int = 512,
        format: str = "WEBP",
        quality: int = 82,
    ) -> DerivedImage:
        return self.transform(
            path,
            source_sha256=source_sha256,
            width=max_size,
            height=max_size,
            fit=FitMode.CONTAIN,
            format=format,
            quality=quality,
            kind="thumbnail",
        )

    def transform(
        self,
        path: str | Path,
        *,
        source_sha256: str,
        width: int,
        height: int,
        fit: FitMode = FitMode.CONTAIN,
        format: str = "JPEG",
        quality: int = 90,
        kind: str = "transform",
        background: str = "#000000",
    ) -> DerivedImage:
        if not 1 <= width <= 16384 or not 1 <= height <= 16384:
            raise ValueError("Image dimensions must be between 1 and 16384 pixels")
        output_format = format.upper()
        if output_format not in _SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported image output format: {format}")
        bounded_quality = max(1, min(int(quality), 100))
        with Image.open(Path(path).resolve(strict=True)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if fit == FitMode.COVER:
                result = ImageOps.fit(image, (width, height), method=_RESAMPLING)
            elif fit == FitMode.PAD:
                result = ImageOps.pad(
                    image,
                    (width, height),
                    method=_RESAMPLING,
                    color=background,
                )
            elif fit == FitMode.STRETCH:
                result = image.resize((width, height), _RESAMPLING)
            else:
                result = image.copy()
                result.thumbnail((width, height), _RESAMPLING)
            if output_format == "JPEG" and result.mode not in {"RGB", "L"}:
                result = result.convert("RGB")
            elif output_format == "WEBP" and result.mode not in {"RGB", "RGBA"}:
                result = result.convert("RGBA" if "A" in result.getbands() else "RGB")
            parameters = {
                "width": width,
                "height": height,
                "fit": fit.value,
                "format": output_format,
                "quality": bounded_quality,
                "background": background,
            }
            suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[output_format]
            descriptor, temporary_name = tempfile.mkstemp(
                prefix="derived-", suffix=suffix, dir=self.store.temp_root
            )
            os.close(descriptor)
            try:
                result.save(temporary_name, format=output_format, quality=bounded_quality)
                stored = self.store.import_file(temporary_name)
            finally:
                Path(temporary_name).unlink(missing_ok=True)
            return DerivedImage(
                source_sha256=source_sha256,
                sha256=stored.sha256,
                object_key=stored.object_key,
                kind=kind,
                format=output_format,
                width=result.width,
                height=result.height,
                parameters=parameters,
            )


def register_image_processors(registry: ProcessorRegistry, catalog: Catalog) -> None:
    store = ContentAddressedStore(catalog.workspace)
    pipeline = ImagePipeline(store)

    def inspect_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        path = store.resolve(item.input_ref)
        analysis = pipeline.inspect(path, sha256=item.input_hash)
        catalog.upsert_image_analysis(analysis)
        if not analysis.valid:
            raise ImageValidationError(analysis.error or "Image inspection failed")
        if analysis.valid and bool(parameters.get("thumbnail", True)):
            thumbnail = pipeline.thumbnail(
                path,
                source_sha256=item.input_hash,
                max_size=int(parameters.get("thumbnail_size", 512)),
            )
            catalog.record_derived_image(thumbnail)
            return {"analysis": asdict(analysis), "thumbnail": asdict(thumbnail)}
        return {"analysis": asdict(analysis)}

    def transform_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        path = store.resolve(item.input_ref)
        derived = pipeline.transform(
            path,
            source_sha256=item.input_hash,
            width=int(parameters.get("width", 1024)),
            height=int(parameters.get("height", 1024)),
            fit=FitMode(str(parameters.get("fit", FitMode.CONTAIN.value))),
            format=str(parameters.get("format", "JPEG")),
            quality=int(parameters.get("quality", 90)),
            background=str(parameters.get("background", "#000000")),
        )
        catalog.record_derived_image(derived)
        return {"derived": asdict(derived)}

    def ocr_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        path = store.resolve(item.input_ref)
        provider = TesseractOCRProvider(
            executable=str(parameters["executable"]) if parameters.get("executable") else None
        )
        if not provider.available() and os.name == "nt" and not parameters.get("executable"):
            from mediasensei.infrastructure.windows_ocr import WindowsOCRProvider
            provider = WindowsOCRProvider()
        action = OCRAction(str(parameters.get("action", OCRAction.DETECT_ONLY.value)))
        analysis = pipeline.inspect(
            path,
            sha256=item.input_hash,
            ocr_provider=provider,
            ocr_language=str(parameters["language"]) if parameters.get("language") else None,
        )
        catalog.upsert_image_analysis(analysis)
        if not analysis.valid:
            raise ImageValidationError(analysis.error or "Image inspection failed")
        if analysis.ocr:
            catalog.apply_ocr_action(item.input_hash, analysis.ocr, action)
        return {"analysis": asdict(analysis), "action": action.value}

    registry.register("image.inspect", inspect_processor)
    registry.register("image.transform", transform_processor)
    registry.register("image.ocr", ocr_processor)


def perceptual_hash(image: Image.Image, *, hash_size: int = 8, high_frequency: int = 4) -> str:
    size = hash_size * high_frequency
    grayscale = image.convert("L").resize((size, size), _RESAMPLING)
    pixels = cast(list[int], list(grayscale.get_flattened_data()))
    cosine = [
        [
            math.cos((2 * coordinate + 1) * frequency * math.pi / (2 * size))
            for coordinate in range(size)
        ]
        for frequency in range(hash_size)
    ]
    coefficients: list[float] = []
    for vertical_frequency in range(hash_size):
        for horizontal_frequency in range(hash_size):
            total = 0.0
            for y in range(size):
                row_offset = y * size
                vertical = cosine[vertical_frequency][y]
                for x in range(size):
                    total += pixels[row_offset + x] * cosine[horizontal_frequency][x] * vertical
            coefficients.append(total)
    threshold = median(coefficients[1:])
    value = 0
    for coefficient in coefficients:
        value = (value << 1) | int(coefficient >= threshold)
    return f"{value:0{hash_size * hash_size // 4}x}"


def phash_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("Perceptual hashes must have the same length")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def blur_score(image: Image.Image) -> float:
    grayscale = image.convert("L")
    grayscale.thumbnail((512, 512), _RESAMPLING)
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ocr_dict(result: OCRResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "confidence": result.confidence,
        "regions": [asdict(region) for region in result.regions],
        "language": result.language,
        "provider": result.provider,
        "provider_version": result.provider_version,
    }
