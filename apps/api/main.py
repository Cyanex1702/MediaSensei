from __future__ import annotations

import importlib.util
import logging
import mimetypes
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from mediasensei import __version__
from mediasensei.domain.acquisition import (
    AcquisitionBudget,
    AcquisitionDecisionKind,
    AcquisitionModality,
    AcquisitionRunState,
    AcquisitionSpec,
    TargetSpec,
    TargetUnit,
)
from mediasensei.domain.documents import DocumentFormat
from mediasensei.domain.images import DatasetSample, FitMode, OCRAction, SplitStrategy
from mediasensei.domain.jobs import (
    ProcessorSpec,
    ResourceHints,
    ResourceLevel,
    RuntimeProfile,
    WorkItem,
)
from mediasensei.domain.media import MediaDerivativeKind, MediaKind
from mediasensei.domain.providers import ProviderImportOptions
from mediasensei.domain.tabular import (
    FilterOperator,
    TabularFilter,
    TabularFormat,
    TabularQuery,
)
from mediasensei.infrastructure.acquisition import (
    AcquisitionService,
    acquisition_processor_spec,
    acquisition_request_hash,
)
from mediasensei.infrastructure.acquisition_discovery import AcquisitionError
from mediasensei.infrastructure.acquisition_planning import spec_from_dict
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.datasets import (
    DatasetSplitter,
    DuplicateDetector,
    LeakageDetector,
    MediaParquetExporter,
)
from mediasensei.infrastructure.documents import SQLiteVectorIndex, document_processor_spec
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.media import media_processor_spec
from mediasensei.infrastructure.plugins import PluginRuntimeManager
from mediasensei.infrastructure.providers import (
    DatasetProviderRegistry,
    provider_processor_spec,
    provider_request_hash,
)
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.infrastructure.tabular import TabularEngine, tabular_processor_spec
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .middleware import RequestBoundary
from .uploads import extract_archive, write_upload

WORKSPACE = settings.workspace
catalog = Catalog(WORKSPACE)
store = ContentAddressedStore(WORKSPACE)
queue = JobQueue(catalog)
providers = DatasetProviderRegistry.defaults()
acquisition = AcquisitionService(catalog)
plugin_runtime = PluginRuntimeManager()
@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("MediaSensei %s starting; workspace=%s", __version__, WORKSPACE)
    yield
    logger.info("MediaSensei API stopped")


app = FastAPI(
    title="MediaSensei API",
    version=__version__,
    lifespan=lifespan,
    description="Versioned local API for MediaSensei clients.",
)
app.add_middleware(RequestBoundary, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("mediasensei.api")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, error: StarletteHTTPException) -> JSONResponse:
    detail = error.detail if isinstance(error.detail, dict) else {"code": f"HTTP_{error.status_code}", "message": str(error.detail)}
    if error.status_code >= 400:
        logger.warning("API request rejected: %s %s", error.status_code, detail.get("code"))
    return JSONResponse(status_code=error.status_code, content={"detail": detail}, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "errors": [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]} for item in error.errors()],
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled MediaSensei API error", exc_info=error)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "INTERNAL_ERROR",
                "message": "Unexpected server error. Check .mediasensei-launcher/logs/api.log for details.",
            }
        },
    )

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
_DOCUMENT_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".html", ".htm"}
_TABULAR_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".parquet", ".xlsx", ".sqlite", ".sqlite3", ".db", ".duckdb"}


class ProjectCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=1000)] = ""
    data_policy: Literal["local_only", "approved_external", "unrestricted"] = "local_only"


class JobInput(BaseModel):
    input_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    input_ref: Annotated[str, Field(min_length=1, max_length=500)]


class JobCreate(BaseModel):
    kind: Annotated[str, Field(min_length=1, max_length=120)]
    processor_id: Annotated[str, Field(min_length=1, max_length=200)] = "core.identity"
    processor_version: Annotated[str, Field(min_length=1, max_length=80)] = "1.0.0"
    deterministic: bool = True
    cacheable: bool = True
    model_revision: Annotated[str | None, Field(max_length=200)] = None
    profile: RuntimeProfile = RuntimeProfile.BALANCED
    cpu: ResourceLevel = ResourceLevel.LOW
    memory: ResourceLevel = ResourceLevel.LOW
    disk: ResourceLevel = ResourceLevel.LOW
    network: ResourceLevel = ResourceLevel.NONE
    gpu: ResourceLevel = ResourceLevel.NONE
    vram: ResourceLevel = ResourceLevel.NONE
    parameters: dict[str, object] = Field(default_factory=dict)
    inputs: Annotated[list[JobInput], Field(min_length=1, max_length=100_000)]


class ProviderImportRequest(BaseModel):
    provider_id: Literal["huggingface", "kaggle"]
    dataset_id: Annotated[
        str,
        Field(
            min_length=3,
            max_length=240,
            pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$",
        ),
    ]
    revision: Annotated[str | None, Field(max_length=200)] = None
    allow_patterns: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=100
    )
    ignore_patterns: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=100
    )
    max_files: Annotated[int, Field(ge=1, le=100_000)] = 10_000
    max_file_bytes: Annotated[int, Field(ge=1, le=100 * 1024**3)] = 2 * 1024**3
    max_total_bytes: Annotated[int, Field(ge=1, le=1024 * 1024**3)] = 20 * 1024**3
    allow_remote: bool = False


class AcquisitionPromptRequest(BaseModel):
    prompt: Annotated[str, Field(min_length=3, max_length=10_000)]


def _default_acquisition_providers() -> list[str]:
    return ["wikimedia-commons", "openverse"]


class AcquisitionSpecRequest(BaseModel):
    allowed_licenses: list[str] = Field(default_factory=list, max_length=50)
    allowed_domains: list[str] = Field(default_factory=list, max_length=50)
    topic: Annotated[str, Field(min_length=1, max_length=500)]
    target_count: Annotated[int, Field(ge=1, le=100_000)] = 100
    categories: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=50
    )
    queries: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=100
    )
    provider_ids: list[
        Annotated[
            str,
            Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
        ]
    ] = Field(default_factory=_default_acquisition_providers, max_length=10)
    min_width: Annotated[int, Field(ge=1, le=100_000)] = 512
    min_height: Annotated[int, Field(ge=1, le=100_000)] = 512
    min_quality: Annotated[float, Field(ge=0, le=100)] = 15
    reject_exact_duplicates: bool = True
    reject_near_duplicates: bool = True
    near_duplicate_threshold: Annotated[int, Field(ge=0, le=64)] = 8
    reject_text_heavy: bool = False
    relevance_strategy: Literal["auto", "metadata", "manual", "disabled"] = "auto"
    replenish_until_target: bool = True
    max_candidates: Annotated[int, Field(ge=1, le=1_000_000)] = 1_500
    max_download_bytes: Annotated[int, Field(ge=1, le=1024 * 1024**3)] = 25 * 1024**3
    max_storage_bytes: Annotated[int, Field(ge=1, le=1024 * 1024**3)] = 20 * 1024**3
    max_requests: Annotated[int, Field(ge=1, le=1_000_000)] = 2_000


class AcquisitionStartRequest(BaseModel):
    allow_remote: bool = False


class AcquisitionTestRequest(BaseModel):
    count: Annotated[int, Field(ge=1, le=100)] = 20
    allow_remote: bool = False


class AcquisitionDecisionRequest(BaseModel):
    decision: Literal["accept", "reject", "review"]


class DocumentIndexRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    max_words: Annotated[int, Field(ge=32, le=4096)] = 420
    overlap_words: Annotated[int, Field(ge=0, le=1024)] = 64


class DocumentSearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    asset_ids: list[str] = Field(default_factory=list, max_length=500)
    limit: Annotated[int, Field(ge=1, le=50)] = 5
    minimum_score: Annotated[float, Field(ge=-1, le=1)] = 0.0


class MediaAnalyzeRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    validate_decode: bool = False
    preview: bool = True


class MediaDeriveRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    kind: MediaDerivativeKind = MediaDerivativeKind.TRANSCODE
    format: Literal["mp4", "webm", "wav", "flac", "mp3", "ogg"] = "mp4"
    start_seconds: Annotated[float | None, Field(ge=0, le=86400)] = None
    duration_seconds: Annotated[float | None, Field(gt=0, le=86400)] = None
    width: Annotated[int | None, Field(ge=64, le=7680)] = None
    height: Annotated[int | None, Field(ge=64, le=4320)] = None


class ImageAnalyzeRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    thumbnail: bool = True
    thumbnail_size: Annotated[int, Field(ge=64, le=2048)] = 512


class ImageTransformRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    width: Annotated[int, Field(ge=1, le=16384)] = 1024
    height: Annotated[int, Field(ge=1, le=16384)] = 1024
    fit: FitMode = FitMode.CONTAIN
    format: Literal["JPEG", "PNG", "WEBP"] = "JPEG"
    quality: Annotated[int, Field(ge=1, le=100)] = 90
    background: Annotated[str, Field(max_length=32)] = "#000000"


class ImageOCRRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100_000)
    action: OCRAction = OCRAction.DETECT_ONLY
    language: Annotated[str | None, Field(max_length=32)] = None


class DatasetSplitRequest(BaseModel):
    strategy: SplitStrategy = SplitStrategy.RANDOM
    seed: int = 42
    train: Annotated[float, Field(ge=0)] = 0.8
    validation: Annotated[float, Field(ge=0)] = 0.1
    test: Annotated[float, Field(ge=0)] = 0.1


class TabularFilterRequest(BaseModel):
    column: Annotated[str, Field(min_length=1, max_length=200)]
    operator: FilterOperator
    value: object | None = None


class TabularQueryRequest(BaseModel):
    filters: list[TabularFilterRequest] = Field(default_factory=list, max_length=100)
    search: Annotated[str | None, Field(max_length=500)] = None
    sort_by: Annotated[str | None, Field(max_length=200)] = None
    descending: bool = False
    visible_columns: list[str] = Field(default_factory=list, max_length=500)
    limit: Annotated[int, Field(ge=1, le=1000)] = 100
    offset: Annotated[int, Field(ge=0)] = 0


class TabularMappingRequest(BaseModel):
    schema_mapping: dict[str, str] = Field(default_factory=dict)
    custom_metadata: dict[str, object] = Field(default_factory=dict)


class TabularExportRequest(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")]
    format: TabularFormat
    query: TabularQueryRequest | None = None


class DatasetExportRequest(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")]


class AssetStateRequest(BaseModel):
    state: Literal["active", "quarantined", "excluded"]


@app.get("/health")
@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {"status": "ok", "version": __version__, "workspace": str(WORKSPACE)}


@app.get("/api/v1/projects")
def list_projects() -> dict[str, object]:
    return {"items": catalog.list_projects()}


@app.post("/api/v1/projects", status_code=201)
def create_project(payload: ProjectCreate) -> dict[str, object]:
    try:
        project = catalog.create_project(payload.name, payload.description, payload.data_policy)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PROJECT", "message": str(error)},
        ) from error
    return {"id": str(project.id), "name": project.name, "data_policy": project.data_policy}


@app.get("/api/v1/dataset-providers")
def list_dataset_providers() -> dict[str, object]:
    return {"items": providers.capabilities()}


@app.get("/api/v1/projects/{project_id}/provider-imports")
def list_provider_imports(project_id: str) -> dict[str, object]:
    try:
        catalog.get_project(project_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": str(error)},
        ) from error
    return {"items": catalog.list_provider_imports(project_id)}


@app.get("/api/v1/provider-imports/{import_id}")
def get_provider_import(import_id: str) -> dict[str, object]:
    try:
        return {
            **catalog.provider_import(import_id),
            "files": catalog.provider_import_files(import_id),
        }
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROVIDER_IMPORT_NOT_FOUND", "message": str(error)},
        ) from error


@app.post("/api/v1/projects/{project_id}/provider-imports", status_code=202)
def create_provider_import(project_id: str, payload: ProviderImportRequest) -> dict[str, object]:
    try:
        project = catalog.get_project(project_id)
        provider = providers.get(payload.provider_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": str(error)},
        ) from error
    except LookupError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROVIDER_NOT_FOUND", "message": str(error)},
        ) from error
    if not payload.allow_remote:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REMOTE_PERMISSION_REQUIRED",
                "message": "Set allow_remote=true to authorize this network import.",
            },
        )
    if project["data_policy"] == "local_only":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PROJECT_POLICY_BLOCKED",
                "message": "This project is local-only; create or use an approved_external project.",
            },
        )
    if not provider.available():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROVIDER_UNAVAILABLE",
                "message": "Install the provider extra before queueing this import.",
            },
        )
    try:
        options = ProviderImportOptions(
            allow_patterns=tuple(payload.allow_patterns),
            ignore_patterns=tuple(payload.ignore_patterns),
            max_files=payload.max_files,
            max_file_bytes=payload.max_file_bytes,
            max_total_bytes=payload.max_total_bytes,
        )
        revision = payload.revision.strip() if payload.revision else None
        import_id = catalog.create_provider_import(
            project_id=project_id,
            provider_id=provider.provider_id,
            dataset_id=payload.dataset_id,
            requested_revision=revision,
            allow_patterns=options.allow_patterns,
            ignore_patterns=options.ignore_patterns,
            max_files=options.max_files,
            max_file_bytes=options.max_file_bytes,
            max_total_bytes=options.max_total_bytes,
        )
        request_hash = provider_request_hash(
            provider.provider_id, payload.dataset_id, revision, options
        )
        job = queue.enqueue(
            project_id=project_id,
            kind="dataset-provider-import",
            processor=provider_processor_spec(),
            items=[WorkItem(request_hash, import_id, 0)],
            parameters={"import_id": import_id},
            profile=RuntimeProfile.BALANCED,
        )
        return {"import": catalog.provider_import(import_id), "job": _job_response(job)}
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PROVIDER_IMPORT", "message": str(error)},
        ) from error


@app.get("/api/v1/projects/{project_id}/assets")
def list_project_assets(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    items: list[dict[str, object]] = []
    for asset in catalog.list_assets(project_id, state=None):
        item = dict(asset)
        sha256 = str(asset["sha256"])
        media_type = str(asset["media_type"])
        if media_type == "image":
            item["analysis"] = catalog.image_analysis(sha256)
            image_derivatives = catalog.derived_images(sha256)
            thumbnails = [entry for entry in image_derivatives if str(entry.get("kind")) == "thumbnail"]
            item["thumbnail_available"] = bool(thumbnails)
            item["derivatives"] = image_derivatives
        elif media_type in {MediaKind.VIDEO.value, MediaKind.AUDIO.value}:
            item["analysis"] = catalog.media_analysis(sha256)
            item["derivatives"] = catalog.derived_media(sha256)
        items.append(item)
    return {"items": items}


@app.get("/api/v1/derived/images/{derived_id}/content")
def derived_image_content(derived_id: str):
    try:
        item = catalog.get_derived_image(derived_id)
        path = store.resolve(str(item["object_key"]))
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DERIVED_IMAGE_NOT_FOUND", "message": str(error)}
        ) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(
            status_code=404, detail={"code": "DERIVED_CONTENT_MISSING", "message": str(error)}
        ) from error
    media_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
        str(item.get("format", "")).upper(), "application/octet-stream"
    )
    suffix = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(
        str(item.get("format", "")).upper(), "bin"
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{item.get('kind', 'derived')}-{derived_id}.{suffix}",
    )


@app.get("/api/v1/derived/media/{derived_id}/content")
def derived_media_content(derived_id: str):
    try:
        item = catalog.get_derived_media(derived_id)
        path = store.resolve(str(item["object_key"]))
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DERIVED_MEDIA_NOT_FOUND", "message": str(error)}
        ) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(
            status_code=404, detail={"code": "DERIVED_CONTENT_MISSING", "message": str(error)}
        ) from error
    return FileResponse(
        path,
        media_type=str(item.get("mime_type") or "application/octet-stream"),
        filename=f"{item.get('kind', 'derived')}-{derived_id}.{item.get('format', 'bin')}",
    )


@app.patch("/api/v1/assets/{asset_id}")
def update_asset_state(asset_id: str, payload: AssetStateRequest) -> dict[str, object]:
    try:
        return catalog.set_asset_state(asset_id, payload.state)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ASSET_NOT_FOUND", "message": str(error)}
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_ASSET_STATE", "message": str(error)}
        ) from error


@app.get("/api/v1/assets/{asset_id}/content")
def asset_content(asset_id: str):
    try:
        asset = catalog.get_asset(asset_id)
        path = store.resolve(str(asset["object_key"]))
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ASSET_NOT_FOUND", "message": str(error)}
        ) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(
            status_code=404, detail={"code": "ASSET_CONTENT_MISSING", "message": str(error)}
        ) from error
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    content_type = str(metadata.get("content_type") or "")
    if not content_type or content_type == "None":
        content_type = mimetypes.guess_type(str(asset["original_filename"]))[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=content_type,
        filename=str(asset["original_filename"]),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/v1/assets/{asset_id}/thumbnail")
def asset_thumbnail(asset_id: str):
    try:
        asset = catalog.get_asset(asset_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ASSET_NOT_FOUND", "message": str(error)}
        ) from error
    if str(asset["media_type"]) != "image":
        raise HTTPException(
            status_code=422,
            detail={"code": "NOT_AN_IMAGE", "message": "Only image assets have image thumbnails"},
        )
    thumbnails = catalog.derived_images(str(asset["sha256"]), kind="thumbnail")
    if not thumbnails:
        raise HTTPException(
            status_code=404,
            detail={"code": "THUMBNAIL_NOT_READY", "message": "Thumbnail has not been generated yet"},
        )
    thumbnail = thumbnails[0]
    try:
        path = store.resolve(str(thumbnail["object_key"]))
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(
            status_code=404, detail={"code": "THUMBNAIL_MISSING", "message": str(error)}
        ) from error
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.post("/api/v1/projects/{project_id}/assets", status_code=202)
def import_asset(project_id: str, file: UploadFile) -> dict[str, object]:
    _require_project(project_id)
    safe_name = Path((file.filename or "upload.bin").replace("\\", "/")).name
    if Path(safe_name).suffix.lower() == ".zip":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ZIP_USE_ARCHIVE_ENDPOINT",
                "message": "Upload ZIP files to /imports/archive so they can be safely extracted",
            },
        )
    temporary = _write_upload(file, max_bytes=settings.max_upload_bytes)
    try:
        asset = _import_local_path(
            project_id, temporary, safe_name=safe_name, content_type=file.content_type
        )
        jobs = _queue_imported_assets(project_id, [asset])
        return {"asset": asset, "jobs": jobs}
    finally:
        temporary.unlink(missing_ok=True)


@app.post("/api/v1/projects/{project_id}/imports/archive", status_code=202)
def import_archive(project_id: str, file: UploadFile) -> dict[str, object]:
    _require_project(project_id)
    safe_name = Path(file.filename or "dataset.zip").name
    if Path(safe_name).suffix.lower() != ".zip":
        raise HTTPException(
            status_code=422,
            detail={"code": "NOT_A_ZIP", "message": "Archive import currently supports .zip files"},
        )
    temporary = _write_upload(file, max_bytes=settings.max_upload_bytes)
    try:
        with extract_archive(temporary, WORKSPACE / "temp", settings, _classify_filename) as (members, skipped):
            imported = [
                _import_local_path(project_id, path, safe_name=name, content_type=None)
                for path, name in members
            ]
            jobs = _queue_imported_assets(project_id, imported)
            logger.info("ZIP imported: files=%d skipped=%d", len(imported), len(skipped))
            return {"archive": safe_name, "imported_count": len(imported),
                    "skipped_count": len(skipped), "items": imported,
                    "skipped": skipped[:200], "jobs": jobs}
    finally:
        temporary.unlink(missing_ok=True)


@app.post("/api/v1/projects/{project_id}/documents", status_code=202)
def import_document(project_id: str, file: UploadFile) -> dict[str, object]:
    _require_project(project_id)
    safe_name = Path(file.filename or "upload.txt").name
    try:
        document_format = DocumentFormat.from_filename(safe_name)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSUPPORTED_DOCUMENT", "message": str(error)},
        ) from error
    temporary = _write_upload(file, max_bytes=settings.max_upload_bytes)
    try:
        stored = store.import_file(temporary)
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=safe_name,
            media_type="document",
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"content_type": file.content_type, "format": document_format.value},
        )
        asset = catalog.get_asset(asset_id)
        job = _enqueue_document_index(project_id, [asset], max_words=420, overlap_words=64)
        return {"asset_id": asset_id, "sha256": stored.sha256, "job": _job_response(job)}
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/api/v1/projects/{project_id}/documents")
def list_project_documents(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    return {
        "items": catalog.list_document_indexes(project_id),
        "stats": catalog.document_stats(project_id),
    }


@app.post("/api/v1/projects/{project_id}/documents/index", status_code=202)
def index_documents(project_id: str, payload: DocumentIndexRequest) -> dict[str, object]:
    if payload.overlap_words >= payload.max_words:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CHUNKING",
                "message": "Overlap must be smaller than chunk size",
            },
        )
    assets = _selected_documents(project_id, payload.asset_ids)
    return _job_response(
        _enqueue_document_index(
            project_id,
            assets,
            max_words=payload.max_words,
            overlap_words=payload.overlap_words,
        )
    )


@app.get("/api/v1/documents/{asset_id}/chunks")
def list_document_chunks(asset_id: str, limit: int = 200) -> dict[str, object]:
    try:
        asset = catalog.get_asset(asset_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": str(error)},
        ) from error
    if asset["media_type"] != "document":
        raise HTTPException(
            status_code=422,
            detail={"code": "NOT_A_DOCUMENT", "message": "The selected asset is not a document"},
        )
    return {"items": catalog.document_chunks(asset_id, limit=limit)}


@app.post("/api/v1/projects/{project_id}/documents/search")
def search_documents(project_id: str, payload: DocumentSearchRequest) -> dict[str, object]:
    try:
        hits = SQLiteVectorIndex(catalog).search(
            project_id,
            payload.query,
            limit=payload.limit,
            minimum_score=payload.minimum_score,
            asset_ids=payload.asset_ids,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_RETRIEVAL", "message": str(error)},
        ) from error
    return {
        "query": payload.query,
        "items": [asdict(hit) for hit in hits],
        "stats": catalog.document_stats(project_id),
    }


@app.post("/api/v1/projects/{project_id}/media", status_code=202)
def import_media(project_id: str, file: UploadFile) -> dict[str, object]:
    _require_project(project_id)
    safe_name = Path((file.filename or "upload.bin").replace("\\", "/")).name
    extension = Path(safe_name).suffix.lower()
    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    audio_extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
    if extension in video_extensions:
        media_type = MediaKind.VIDEO.value
    elif extension in audio_extensions:
        media_type = MediaKind.AUDIO.value
    else:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSUPPORTED_MEDIA", "message": "Use a supported video or audio file"},
        )
    temporary = _write_upload(file, max_bytes=settings.max_upload_bytes)
    try:
        stored = store.import_file(temporary)
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=safe_name,
            media_type=media_type,
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"content_type": file.content_type},
        )
        job = _enqueue_media_operation(
            project_id,
            [catalog.get_asset(asset_id)],
            processor_id="media.inspect",
            kind="media-inspection",
            parameters={"preview": True},
        )
        return {"asset_id": asset_id, "sha256": stored.sha256, "job": _job_response(job)}
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/api/v1/projects/{project_id}/media")
def list_project_media(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    items: list[dict[str, object]] = []
    for asset in _project_media_assets(project_id, state=None):
        sha256 = str(asset["sha256"])
        items.append(
            {
                **asset,
                "analysis": catalog.media_analysis(sha256),
                "derivatives": catalog.derived_media(sha256),
            }
        )
    return {"items": items}


@app.post("/api/v1/projects/{project_id}/media/analyze", status_code=202)
def analyze_media(project_id: str, payload: MediaAnalyzeRequest) -> dict[str, object]:
    assets = _selected_media(project_id, payload.asset_ids)
    job = _enqueue_media_operation(
        project_id,
        assets,
        processor_id="media.inspect",
        kind="media-inspection",
        parameters={"validate_decode": payload.validate_decode, "preview": payload.preview},
    )
    return _job_response(job)


@app.post("/api/v1/projects/{project_id}/media/derive", status_code=202)
def derive_media(project_id: str, payload: MediaDeriveRequest) -> dict[str, object]:
    if payload.kind == MediaDerivativeKind.CLIP and (
        payload.start_seconds is None and payload.duration_seconds is None
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CLIP", "message": "A clip needs a start or duration"},
        )
    assets = _selected_media(project_id, payload.asset_ids)
    items: list[dict[str, object]] = []
    for asset in assets:
        media_kind = MediaKind(str(asset["media_type"]))
        if payload.kind == MediaDerivativeKind.THUMBNAIL and media_kind != MediaKind.VIDEO:
            continue
        if payload.kind == MediaDerivativeKind.WAVEFORM and media_kind != MediaKind.AUDIO:
            continue
        if payload.kind in {MediaDerivativeKind.TRANSCODE, MediaDerivativeKind.CLIP}:
            allowed = (
                {"mp4", "webm"} if media_kind == MediaKind.VIDEO else {"wav", "flac", "mp3", "ogg"}
            )
            if payload.format not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_MEDIA_FORMAT",
                        "message": f"{payload.format} is not valid for {media_kind.value}",
                    },
                )
        items.append(asset)
    if not items:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_COMPATIBLE_MEDIA",
                "message": "No selected assets support that derivative",
            },
        )
    parameters: dict[str, object] = {
        "kind": payload.kind.value,
        "format": payload.format,
        "start_seconds": payload.start_seconds,
        "duration_seconds": payload.duration_seconds,
        "width": payload.width,
        "height": payload.height,
    }
    job = _enqueue_media_operation(
        project_id,
        items,
        processor_id="media.derive",
        kind="media-derivative",
        parameters=parameters,
        include_media_kind=True,
    )
    return _job_response(job)


@app.post("/api/v1/projects/{project_id}/tabular", status_code=202)
def import_tabular_dataset(
    project_id: str,
    file: UploadFile,
    source_format: TabularFormat | None = None,
    sheet: str | None = None,
    table: str | None = None,
) -> dict[str, object]:
    _require_project(project_id)
    safe_name = Path(file.filename or "upload.csv").name
    try:
        selected_format = source_format or TabularFormat.from_filename(safe_name)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_FORMAT", "message": str(error)}
        ) from error
    temporary = _write_upload(file, max_bytes=settings.max_upload_bytes)
    try:
        stored = store.import_file(temporary)
        options = {key: value for key, value in {"sheet": sheet, "table": table}.items() if value}
        asset_id = catalog.record_asset(
            project_id=project_id,
            sha256=stored.sha256,
            original_filename=safe_name,
            media_type="tabular",
            object_key=stored.object_key,
            byte_size=stored.byte_size,
            metadata={"content_type": file.content_type, "format": selected_format.value},
        )
        analysis_key = TabularEngine.analysis_key(stored.sha256, selected_format, options)
        dataset_id = catalog.record_tabular_dataset(
            project_id=project_id,
            asset_id=asset_id,
            analysis_key=analysis_key,
            name=Path(safe_name).stem,
        )
        job = queue.enqueue(
            project_id=project_id,
            kind="tabular-inspection",
            processor=tabular_processor_spec(),
            items=[WorkItem(stored.sha256, stored.object_key, 0)],
            parameters={"source_format": selected_format.value, **options},
        )
        return {"dataset_id": dataset_id, "asset_id": asset_id, "job": _job_response(job)}
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/api/v1/projects/{project_id}/tabular")
def list_tabular_datasets(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    return {"items": catalog.list_tabular_datasets(project_id)}


@app.get("/api/v1/tabular/{dataset_id}")
def get_tabular_dataset(dataset_id: str) -> dict[str, object]:
    try:
        return catalog.get_tabular_dataset(dataset_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DATASET_NOT_READY", "message": str(error)}
        ) from error


@app.post("/api/v1/tabular/{dataset_id}/query")
def query_tabular_dataset(dataset_id: str, payload: TabularQueryRequest) -> dict[str, object]:
    try:
        dataset = catalog.get_tabular_dataset(dataset_id)
        request = _tabular_query(payload)
        started = time.perf_counter()
        result = TabularEngine(store).query(str(dataset["normalized_object_key"]), request)
        duration_ms = (time.perf_counter() - started) * 1000
        catalog.record_tabular_query(
            dataset_id, payload.model_dump(), int(result["total"]), duration_ms
        )
        return {**result, "duration_ms": round(duration_ms, 3)}
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DATASET_NOT_FOUND", "message": str(error)}
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_QUERY", "message": str(error)}
        ) from error


@app.get("/api/v1/tabular/{dataset_id}/frequency/{column}")
def tabular_frequency(dataset_id: str, column: str, limit: int = 20) -> dict[str, object]:
    try:
        dataset = catalog.get_tabular_dataset(dataset_id)
        items = TabularEngine(store).frequency(
            str(dataset["normalized_object_key"]), column, limit=max(1, min(limit, 100))
        )
        return {"column": column, "items": items}
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DATASET_NOT_FOUND", "message": str(error)}
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_COLUMN", "message": str(error)}
        ) from error


@app.put("/api/v1/tabular/{dataset_id}/mapping")
def update_tabular_mapping(dataset_id: str, payload: TabularMappingRequest) -> dict[str, object]:
    try:
        return catalog.update_tabular_mapping(
            dataset_id,
            schema_mapping=payload.schema_mapping,
            custom_metadata=payload.custom_metadata,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DATASET_NOT_FOUND", "message": str(error)}
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_MAPPING", "message": str(error)}
        ) from error


@app.post("/api/v1/tabular/{dataset_id}/export", status_code=201)
def export_tabular_dataset(dataset_id: str, payload: TabularExportRequest) -> dict[str, object]:
    try:
        dataset = catalog.get_tabular_dataset(dataset_id)
        suffix = {TabularFormat.SQLITE: "sqlite", TabularFormat.DUCKDB: "duckdb"}.get(
            payload.format, payload.format.value
        )
        destination = WORKSPACE / "exports" / f"{payload.name}.{suffix}"
        result = TabularEngine(store).export(
            str(dataset["normalized_object_key"]),
            destination,
            payload.format,
            query=_tabular_query(payload.query) if payload.query else None,
        )
        export_id = catalog.record_tabular_export(dataset_id, result)
        return {"id": export_id, **asdict(result)}
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DATASET_NOT_FOUND", "message": str(error)}
        ) from error
    except (ValueError, FileExistsError) as error:
        raise HTTPException(
            status_code=409, detail={"code": "EXPORT_FAILED", "message": str(error)}
        ) from error


@app.post("/api/v1/projects/{project_id}/jobs", status_code=202)
def enqueue_job(project_id: str, payload: JobCreate) -> dict[str, object]:
    _require_project(project_id)
    processor = ProcessorSpec(
        id=payload.processor_id,
        version=payload.processor_version,
        deterministic=payload.deterministic,
        cacheable=payload.cacheable,
        model_revision=payload.model_revision,
        resource_hints=ResourceHints(
            cpu=payload.cpu,
            memory=payload.memory,
            disk=payload.disk,
            network=payload.network,
            gpu=payload.gpu,
            vram=payload.vram,
        ),
    )
    try:
        job = queue.enqueue(
            project_id=project_id,
            kind=payload.kind,
            processor=processor,
            items=[
                WorkItem(
                    input_hash=item.input_hash,
                    input_ref=item.input_ref,
                    position=position,
                )
                for position, item in enumerate(payload.inputs)
            ],
            parameters=payload.parameters,
            profile=payload.profile,
        )
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_JOB", "message": str(error)},
        ) from error
    return _job_response(job)


@app.get("/api/v1/projects/{project_id}/images")
def list_project_images(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    items = []
    for asset in catalog.list_assets(project_id, media_type="image", state=None):
        items.append(
            {
                **asset,
                "analysis": catalog.image_analysis(str(asset["sha256"])),
            }
        )
    return {"items": items}


@app.post("/api/v1/projects/{project_id}/images/analyze", status_code=202)
def analyze_images(project_id: str, payload: ImageAnalyzeRequest) -> dict[str, object]:
    assets = _selected_images(project_id, payload.asset_ids)
    return _job_response(
        _enqueue_image_operation(
            project_id,
            assets,
            processor_id="image.inspect",
            kind="image-inspection",
            parameters={
                "thumbnail": payload.thumbnail,
                "thumbnail_size": payload.thumbnail_size,
            },
        )
    )


@app.post("/api/v1/projects/{project_id}/images/transform", status_code=202)
def transform_images(project_id: str, payload: ImageTransformRequest) -> dict[str, object]:
    assets = _selected_images(project_id, payload.asset_ids)
    return _job_response(
        _enqueue_image_operation(
            project_id,
            assets,
            processor_id="image.transform",
            kind="image-transform",
            parameters={
                "width": payload.width,
                "height": payload.height,
                "fit": payload.fit.value,
                "format": payload.format,
                "quality": payload.quality,
                "background": payload.background,
            },
        )
    )


@app.post("/api/v1/projects/{project_id}/images/ocr", status_code=202)
def ocr_images(project_id: str, payload: ImageOCRRequest) -> dict[str, object]:
    assets = _selected_images(project_id, payload.asset_ids)
    return _job_response(
        _enqueue_image_operation(
            project_id,
            assets,
            processor_id="image.ocr",
            kind="image-ocr",
            parameters={"action": payload.action.value, "language": payload.language},
            deterministic=False,
        )
    )


@app.post("/api/v1/projects/{project_id}/images/duplicates")
def detect_duplicates(project_id: str, threshold: int = 8) -> dict[str, object]:
    groups = DuplicateDetector().groups(
        _project_image_samples(project_id),
        perceptual_threshold=max(0, min(threshold, 64)),
    )
    catalog.replace_duplicate_groups(project_id, groups)
    return {"items": groups, "count": len(groups)}


@app.post("/api/v1/projects/{project_id}/dataset/split")
def split_dataset(project_id: str, payload: DatasetSplitRequest) -> dict[str, object]:
    assigned = DatasetSplitter().assign(
        _project_image_samples(project_id),
        strategy=payload.strategy,
        seed=payload.seed,
        ratios={
            "train": payload.train,
            "validation": payload.validation,
            "test": payload.test,
        },
    )
    catalog.replace_dataset_samples(
        project_id,
        assigned,
        seed=payload.seed,
        strategy=payload.strategy.value,
    )
    counts: dict[str, int] = {}
    for sample in assigned:
        split = sample.split or "unassigned"
        counts[split] = counts.get(split, 0) + 1
    return {"seed": payload.seed, "strategy": payload.strategy.value, "counts": counts}


@app.post("/api/v1/projects/{project_id}/dataset/leakage")
def check_dataset_leakage(project_id: str, threshold: int = 8) -> dict[str, object]:
    _require_project(project_id)
    issues = LeakageDetector().detect(
        catalog.dataset_samples(project_id),
        perceptual_threshold=max(0, min(threshold, 64)),
    )
    catalog.replace_leakage_issues(project_id, issues)
    return {"items": [asdict(issue) for issue in issues], "count": len(issues)}


@app.post("/api/v1/projects/{project_id}/dataset/export", status_code=201)
def export_image_dataset(project_id: str, payload: DatasetExportRequest) -> dict[str, object]:
    _require_project(project_id)
    try:
        result = MediaParquetExporter(store).export(
            catalog.dataset_samples(project_id),
            WORKSPACE / "exports" / payload.name,
            project_name=project_id,
            split_seed=42,
        )
        export_id = catalog.record_export(project_id, result)
        return {"id": export_id, **asdict(result)}
    except (ValueError, FileExistsError, RuntimeError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "EXPORT_FAILED", "message": str(error)},
        ) from error


@app.get("/api/v1/projects/{project_id}/dataset/exports")
def list_image_dataset_exports(project_id: str) -> dict[str, object]:
    _require_project(project_id)
    return {"items": catalog.list_dataset_exports(project_id)}


@app.get("/api/v1/dataset/exports/{export_id}/download")
def download_image_dataset_export(export_id: str):
    try:
        item = catalog.get_dataset_export(export_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "EXPORT_NOT_FOUND", "message": str(error)}
        ) from error
    source = Path(str(item["path"])).resolve()
    export_root = (WORKSPACE / "exports").resolve()
    try:
        source.relative_to(export_root)
    except ValueError as error:
        raise HTTPException(
            status_code=403, detail={"code": "INVALID_EXPORT_PATH", "message": "Export path escapes workspace"}
        ) from error
    if not source.exists():
        raise HTTPException(
            status_code=404, detail={"code": "EXPORT_MISSING", "message": "Export no longer exists on disk"}
        )
    if source.is_file():
        return FileResponse(source, filename=source.name, media_type="application/octet-stream")
    download_root = WORKSPACE / "temp" / "downloads"
    download_root.mkdir(parents=True, exist_ok=True)
    archive_base = download_root / f"dataset-{export_id}-{uuid.uuid4().hex}"
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=source))
    return FileResponse(
        archive_path,
        filename=f"{source.name}.zip",
        media_type="application/zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/tabular/exports/{export_id}/download")
def download_tabular_export(export_id: str):
    try:
        item = catalog.get_tabular_export(export_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail={"code": "EXPORT_NOT_FOUND", "message": str(error)}
        ) from error
    source = Path(str(item["path"])).resolve()
    export_root = (WORKSPACE / "exports").resolve()
    try:
        source.relative_to(export_root)
    except ValueError as error:
        raise HTTPException(
            status_code=403, detail={"code": "INVALID_EXPORT_PATH", "message": "Export path escapes workspace"}
        ) from error
    if not source.is_file():
        raise HTTPException(
            status_code=404, detail={"code": "EXPORT_MISSING", "message": "Export no longer exists on disk"}
        )
    return FileResponse(source, filename=source.name, media_type="application/octet-stream")


@app.get("/api/v1/plugins")
def list_plugins() -> dict[str, object]:
    return plugin_runtime.snapshot()


@app.post("/api/v1/plugins/rescan")
def rescan_plugins() -> dict[str, object]:
    return plugin_runtime.reload()


@app.get("/api/v1/acquisition/providers")
def acquisition_providers(project_id: str | None = None) -> dict[str, object]:
    try:
        return acquisition.capabilities(project_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": str(error)},
        ) from error


@app.post("/api/v1/projects/{project_id}/acquisition/requests", status_code=201)
def create_acquisition_from_prompt(
    project_id: str,
    payload: AcquisitionPromptRequest,
) -> dict[str, object]:
    try:
        request_id, plan_id = acquisition.from_prompt(project_id, payload.prompt)
        return {
            "request_id": request_id,
            "plan": acquisition.repository.plan(plan_id),
        }
    except (KeyError, ValueError) as error:
        status = 404 if isinstance(error, KeyError) else 422
        raise HTTPException(
            status_code=status,
            detail={"code": "INVALID_ACQUISITION_REQUEST", "message": str(error)},
        ) from error


@app.post("/api/v1/projects/{project_id}/acquisition/plans", status_code=201)
def create_acquisition_plan(
    project_id: str,
    payload: AcquisitionSpecRequest,
) -> dict[str, object]:
    try:
        for provider_id in payload.provider_ids:
            acquisition.discovery.get(provider_id)
        spec = AcquisitionSpec(
            AcquisitionModality.IMAGE,
            payload.topic,
            TargetSpec(TargetUnit.ACCEPTED_ASSETS, payload.target_count),
            allowed_licenses=tuple(v.strip().casefold() for v in payload.allowed_licenses if v.strip()),
            allowed_domains=tuple(v.strip().casefold() for v in payload.allowed_domains if v.strip()),
            categories=tuple(payload.categories),
            queries=tuple(payload.queries),
            provider_ids=tuple(payload.provider_ids),
            min_width=payload.min_width,
            min_height=payload.min_height,
            min_quality=payload.min_quality,
            reject_exact_duplicates=payload.reject_exact_duplicates,
            reject_near_duplicates=payload.reject_near_duplicates,
            near_duplicate_threshold=payload.near_duplicate_threshold,
            reject_text_heavy=payload.reject_text_heavy,
            relevance_strategy=payload.relevance_strategy,
            replenish_until_target=payload.replenish_until_target,
            budget=AcquisitionBudget(
                max_candidates=payload.max_candidates,
                max_download_bytes=payload.max_download_bytes,
                max_storage_bytes=payload.max_storage_bytes,
                max_requests=payload.max_requests,
            ),
        )
        request_id, plan_id = acquisition.create_plan(project_id, spec)
        return {
            "request_id": request_id,
            "plan": acquisition.repository.plan(plan_id),
        }
    except (ValueError, LookupError) as error:
        status = 404 if isinstance(error, KeyError) else 422
        raise HTTPException(
            status_code=status,
            detail={"code": "INVALID_ACQUISITION_PLAN", "message": str(error)},
        ) from error


@app.get("/api/v1/acquisition/plans/{plan_id}")
def get_acquisition_plan(plan_id: str) -> dict[str, object]:
    try:
        return acquisition.repository.plan(plan_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_PLAN_NOT_FOUND", "message": str(error)},
        ) from error


@app.post("/api/v1/acquisition/plans/{plan_id}/start", status_code=202)
def start_acquisition(
    plan_id: str,
    payload: AcquisitionStartRequest,
) -> dict[str, object]:
    return _start_acquisition_run(plan_id, payload.allow_remote)


@app.post("/api/v1/acquisition/plans/{plan_id}/test", status_code=202)
def test_acquisition(
    plan_id: str,
    payload: AcquisitionTestRequest,
) -> dict[str, object]:
    return _start_acquisition_run(
        plan_id,
        payload.allow_remote,
        dry_run_count=payload.count,
    )


@app.get("/api/v1/acquisition/runs/{run_id}")
def get_acquisition_run(run_id: str) -> dict[str, object]:
    try:
        return {
            **acquisition.repository.run(run_id),
            "rejections": acquisition.repository.rejection_summary(run_id),
        }
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_RUN_NOT_FOUND", "message": str(error)},
        ) from error


@app.get("/api/v1/acquisition/runs/{run_id}/candidates")
def list_acquisition_candidates(
    run_id: str,
    state: str | None = None,
    reason: str | None = None,
    limit: int = 500,
) -> dict[str, object]:
    try:
        acquisition.repository.run(run_id)
        return {
            "items": acquisition.repository.list_candidates(
                run_id,
                state=state,
                reason=reason,
                limit=limit,
            )
        }
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_RUN_NOT_FOUND", "message": str(error)},
        ) from error


@app.post("/api/v1/acquisition/candidates/{candidate_id}/decision")
def decide_acquisition_candidate(
    candidate_id: str,
    payload: AcquisitionDecisionRequest,
) -> dict[str, object]:
    try:
        return acquisition.human_decision(
            candidate_id,
            AcquisitionDecisionKind(payload.decision),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_CANDIDATE_NOT_FOUND", "message": str(error)},
        ) from error
    except (ValueError, AcquisitionError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_ACQUISITION_DECISION", "message": str(error)},
        ) from error


@app.post("/api/v1/acquisition/runs/{run_id}/{action}")
def control_acquisition_run(
    run_id: str,
    action: Literal["pause", "resume", "cancel"],
) -> dict[str, object]:
    try:
        run = acquisition.repository.run(run_id)
        job_id = str(run["job_id"] or "")
        if action == "pause":
            acquisition.repository.set_run_state(run_id, AcquisitionRunState.PAUSED)
            if job_id:
                queue.pause(job_id)
        elif action == "resume":
            acquisition.repository.set_run_state(run_id, AcquisitionRunState.REPLENISHING)
            if job_id:
                queue.retry_failed(job_id)
                queue.resume(job_id)
        else:
            acquisition.repository.set_run_state(run_id, AcquisitionRunState.CANCELLED)
            if job_id:
                queue.cancel(job_id)
        return acquisition.repository.run(run_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_RUN_NOT_FOUND", "message": str(error)},
        ) from error


@app.get("/api/v1/jobs")
def list_jobs(project_id: str | None = None, limit: int = 100) -> dict[str, object]:
    if project_id is not None:
        _require_project(project_id)
    return {"items": [_job_response(job) for job in queue.list_jobs(project_id, limit=limit)]}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    return _get_job(job_id)


@app.get("/api/v1/jobs/{job_id}/events")
def get_job_events(job_id: str, limit: int = 100) -> dict[str, object]:
    _get_job(job_id)
    return {"items": queue.events(job_id, limit=limit)}


@app.post("/api/v1/jobs/{job_id}/{action}")
def control_job(
    job_id: str,
    action: Literal["pause", "resume", "cancel", "retry-failed"],
) -> dict[str, object]:
    try:
        if action == "pause":
            job = queue.pause(job_id)
        elif action == "resume":
            job = queue.resume(job_id)
        elif action == "cancel":
            job = queue.cancel(job_id)
        else:
            job = queue.retry_failed(job_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": str(error)},
        ) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(409, detail={"code": "INVALID_JOB_STATE", "message": str(error)}) from error
    return _job_response(job)


@app.get("/api/v1/cache/stats")
def cache_stats() -> dict[str, int]:
    return queue.cache_stats()


@app.get("/api/v1/system/capabilities")
def system_capabilities() -> dict[str, object]:
    return {
        "ffmpeg": os.environ.get("MEDIASENSEI_FFMPEG") or shutil.which("ffmpeg"),
        "ffprobe": os.environ.get("MEDIASENSEI_FFPROBE") or shutil.which("ffprobe"),
        "tesseract": os.environ.get("MEDIASENSEI_TESSERACT") or shutil.which("tesseract"),
        "windows_ocr": os.name == "nt",
        "duckdb": importlib.util.find_spec("duckdb") is not None,
        "pyarrow": importlib.util.find_spec("pyarrow") is not None,
        "pillow": importlib.util.find_spec("PIL") is not None,
    }


@app.get("/api/v1/system/logs")
def system_logs(lines: int = 200) -> dict[str, object]:
    bounded_lines = max(20, min(lines, 2000))
    root = Path(__file__).resolve().parents[2]
    log_dir = root / ".mediasensei-launcher" / "logs"
    result: dict[str, str] = {}
    for name in ("api", "worker", "web"):
        path = log_dir / f"{name}.log"
        if not path.is_file():
            result[name] = ""
            continue
        try:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 256 * 1024))
                text = stream.read().decode("utf-8", errors="replace")
            result[name] = "\n".join(text.splitlines()[-bounded_lines:])
        except OSError as error:
            result[name] = f"Unable to read log: {error}"
    return {"log_dir": str(log_dir), "logs": result}


def _require_project(project_id: str) -> dict[str, object]:
    try:
        return catalog.get_project(project_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": str(error)},
        ) from error


def _write_upload(file: UploadFile, *, max_bytes: int) -> Path:
    return write_upload(file, WORKSPACE / "temp" / "uploads", max_bytes)


def _classify_filename(filename: str) -> str | None:
    extension = Path(filename).suffix.lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _VIDEO_EXTENSIONS:
        return MediaKind.VIDEO.value
    if extension in _AUDIO_EXTENSIONS:
        return MediaKind.AUDIO.value
    if extension in _DOCUMENT_EXTENSIONS:
        return "document"
    if extension in _TABULAR_EXTENSIONS:
        return "tabular"
    return None


def _import_local_path(
    project_id: str,
    path: Path,
    *,
    safe_name: str,
    content_type: str | None,
) -> dict[str, object]:
    _require_project(project_id)
    media_type = _classify_filename(safe_name)
    if media_type is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_ASSET",
                "message": f"Unsupported file type: {Path(safe_name).suffix or safe_name}",
            },
        )
    metadata: dict[str, object] = {
        "content_type": content_type
        or mimetypes.guess_type(safe_name)[0]
        or "application/octet-stream"
    }
    if media_type == "document":
        try:
            metadata["format"] = DocumentFormat.from_filename(safe_name).value
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNSUPPORTED_DOCUMENT", "message": str(error)},
            ) from error
    elif media_type == "tabular":
        try:
            metadata["format"] = TabularFormat.from_filename(safe_name).value
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FORMAT", "message": str(error)},
            ) from error

    if path.stat().st_size == 0:
        raise HTTPException(422, detail={"code": "EMPTY_FILE", "message": "Empty files cannot be imported"})
    stored = store.import_file(path)
    asset_id = catalog.record_asset(
        project_id=project_id,
        sha256=stored.sha256,
        original_filename=safe_name,
        media_type=media_type,
        object_key=stored.object_key,
        byte_size=stored.byte_size,
        metadata=metadata,
    )
    asset = catalog.get_asset(asset_id)
    result: dict[str, object] = {
        **asset,
        "deduplicated": stored.already_existed,
    }
    if media_type == "tabular":
        selected_format = TabularFormat(str(metadata["format"]))
        analysis_key = TabularEngine.analysis_key(stored.sha256, selected_format, {})
        dataset_id = catalog.record_tabular_dataset(
            project_id=project_id,
            asset_id=asset_id,
            analysis_key=analysis_key,
            name=Path(safe_name).stem,
        )
        result["tabular_dataset_id"] = dataset_id
    return result


def _queue_imported_assets(
    project_id: str, imported: list[dict[str, object]]
) -> list[dict[str, object]]:
    if not imported:
        return []
    jobs: list[dict[str, object]] = []
    images = [item for item in imported if str(item.get("media_type")) == "image"]
    documents = [item for item in imported if str(item.get("media_type")) == "document"]
    media = [
        item
        for item in imported
        if str(item.get("media_type")) in {MediaKind.VIDEO.value, MediaKind.AUDIO.value}
    ]
    tabular = [item for item in imported if str(item.get("media_type")) == "tabular"]

    if images:
        jobs.append(
            _job_response(
                _enqueue_image_operation(
                    project_id,
                    images,
                    processor_id="image.inspect",
                    kind="image-inspection",
                    parameters={"thumbnail": True, "thumbnail_size": 512},
                )
            )
        )
    if documents:
        jobs.append(
            _job_response(
                _enqueue_document_index(
                    project_id, documents, max_words=420, overlap_words=64
                )
            )
        )
    if media:
        jobs.append(
            _job_response(
                _enqueue_media_operation(
                    project_id,
                    media,
                    processor_id="media.inspect",
                    kind="media-inspection",
                    parameters={"preview": True, "validate_decode": False},
                )
            )
        )
    for item in tabular:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source_format = str(metadata.get("format") or "")
        if not source_format:
            continue
        job = queue.enqueue(
            project_id=project_id,
            kind="tabular-inspection",
            processor=tabular_processor_spec(),
            items=[
                WorkItem(
                    str(item["sha256"]),
                    str(item["object_key"]),
                    0,
                )
            ],
            parameters={"source_format": source_format},
        )
        jobs.append(_job_response(job))
    return jobs


def _start_acquisition_run(
    plan_id: str,
    allow_remote: bool,
    *,
    dry_run_count: int | None = None,
) -> dict[str, object]:
    if not allow_remote:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REMOTE_PERMISSION_REQUIRED",
                "message": "Set allow_remote=true to authorize this acquisition run.",
            },
        )
    try:
        plan = acquisition.repository.plan(plan_id)
        policy = acquisition.repository.project_policy(str(plan["project_id"]))
        if policy == "local_only":
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "PROJECT_POLICY_BLOCKED",
                    "message": "This project does not allow remote acquisition.",
                },
            )
        run_id = acquisition.repository.create_run(
            plan_id,
            dry_run_count=dry_run_count,
        )
        spec = spec_from_dict(cast(dict[str, object], plan["spec"]))
        job = queue.enqueue(
            project_id=str(plan["project_id"]),
            kind="intelligent-acquisition",
            processor=acquisition_processor_spec(),
            items=[
                WorkItem(
                    acquisition_request_hash(run_id, spec),
                    run_id,
                    0,
                )
            ],
            parameters={"run_id": run_id},
            profile=RuntimeProfile.BALANCED,
        )
        acquisition.repository.attach_job(run_id, job.id)
        return {
            "run": acquisition.repository.run(run_id),
            "job": _job_response(job),
        }
    except HTTPException:
        raise
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACQUISITION_PLAN_NOT_FOUND", "message": str(error)},
        ) from error


def _get_job(job_id: str) -> dict[str, object]:
    try:
        return _job_response(queue.get(job_id))
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": str(error)},
        ) from error


def _selected_documents(project_id: str, asset_ids: list[str]) -> list[dict[str, object]]:
    _require_project(project_id)
    assets = catalog.list_assets(project_id, media_type="document", state="active")
    if asset_ids:
        requested = set(asset_ids)
        assets = [asset for asset in assets if str(asset["id"]) in requested]
        if len(assets) != len(requested):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "DOCUMENT_NOT_FOUND",
                    "message": "One or more documents were not found",
                },
            )
    if not assets:
        raise HTTPException(
            status_code=422,
            detail={"code": "NO_DOCUMENTS", "message": "The project has no active documents"},
        )
    return assets


def _enqueue_document_index(
    project_id: str,
    assets: list[dict[str, object]],
    *,
    max_words: int,
    overlap_words: int,
):
    formats: dict[str, str] = {}
    titles: dict[str, str] = {}
    asset_ids: dict[str, str] = {}
    items: list[WorkItem] = []
    for position, asset in enumerate(assets):
        metadata_value = asset.get("metadata")
        metadata = (
            cast(dict[str, object], metadata_value) if isinstance(metadata_value, dict) else {}
        )
        format_value = str(metadata.get("format", ""))
        if not format_value:
            format_value = DocumentFormat.from_filename(str(asset["original_filename"])).value
        key = str(position)
        asset_ids[key] = str(asset["id"])
        formats[key] = format_value
        titles[key] = Path(str(asset["original_filename"])).stem
        items.append(
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
        )
    return queue.enqueue(
        project_id=project_id,
        kind="document-index",
        processor=document_processor_spec(),
        items=items,
        parameters={
            "asset_ids_by_position": asset_ids,
            "formats_by_position": formats,
            "titles_by_position": titles,
            "max_words": max_words,
            "overlap_words": overlap_words,
        },
        profile=RuntimeProfile.BALANCED,
    )


def _project_media_assets(
    project_id: str, *, state: str | None = "active"
) -> list[dict[str, object]]:
    return [
        *catalog.list_assets(project_id, media_type=MediaKind.VIDEO.value, state=state),
        *catalog.list_assets(project_id, media_type=MediaKind.AUDIO.value, state=state),
    ]


def _selected_media(project_id: str, asset_ids: list[str]) -> list[dict[str, object]]:
    _require_project(project_id)
    assets = _project_media_assets(project_id)
    if asset_ids:
        requested = set(asset_ids)
        assets = [asset for asset in assets if str(asset["id"]) in requested]
        if len(assets) != len(requested):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MEDIA_NOT_FOUND",
                    "message": "One or more media assets were not found",
                },
            )
    if not assets:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_MEDIA",
                "message": "The project has no active video or audio assets",
            },
        )
    return assets


def _enqueue_media_operation(
    project_id: str,
    assets: list[dict[str, object]],
    *,
    processor_id: str,
    kind: str,
    parameters: dict[str, object],
    include_media_kind: bool = False,
):
    if include_media_kind and len({str(asset["media_type"]) for asset in assets}) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MIXED_MEDIA_KINDS",
                "message": "Derive video and audio in separate requests",
            },
        )
    operation_parameters = dict(parameters)
    if include_media_kind:
        operation_parameters["media_kind"] = str(assets[0]["media_type"])
    return queue.enqueue(
        project_id=project_id,
        kind=kind,
        processor=media_processor_spec(processor_id),
        items=[
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
            for position, asset in enumerate(assets)
        ],
        parameters=operation_parameters,
        profile=RuntimeProfile.BALANCED,
    )


def _selected_images(project_id: str, asset_ids: list[str]) -> list[dict[str, object]]:
    _require_project(project_id)
    assets = catalog.list_assets(project_id, media_type="image", state="active")
    if asset_ids:
        requested = set(asset_ids)
        assets = [asset for asset in assets if str(asset["id"]) in requested]
        if len(assets) != len(requested):
            raise HTTPException(
                status_code=404,
                detail={"code": "IMAGE_NOT_FOUND", "message": "One or more images were not found"},
            )
    if not assets:
        raise HTTPException(
            status_code=422,
            detail={"code": "NO_IMAGES", "message": "The project has no active images"},
        )
    return assets


def _enqueue_image_operation(
    project_id: str,
    assets: list[dict[str, object]],
    *,
    processor_id: str,
    kind: str,
    parameters: dict[str, object],
    deterministic: bool = True,
):
    return queue.enqueue(
        project_id=project_id,
        kind=kind,
        processor=ProcessorSpec(
            id=processor_id,
            version="1.0.0",
            deterministic=deterministic,
            cacheable=deterministic,
            resource_hints=ResourceHints(
                cpu=ResourceLevel.MEDIUM,
                memory=ResourceLevel.MEDIUM,
                disk=ResourceLevel.LOW,
            ),
        ),
        items=[
            WorkItem(
                input_hash=str(asset["sha256"]),
                input_ref=str(asset["object_key"]),
                position=position,
            )
            for position, asset in enumerate(assets)
        ],
        parameters=parameters,
        profile=RuntimeProfile.BALANCED,
    )


def _project_image_samples(project_id: str) -> list[DatasetSample]:
    _require_project(project_id)
    samples: list[DatasetSample] = []
    for asset in catalog.list_assets(project_id, media_type="image", state="active"):
        analysis = catalog.image_analysis(str(asset["sha256"])) or {}
        metadata = (
            cast(dict[str, object], asset["metadata"])
            if isinstance(asset.get("metadata"), dict)
            else {}
        )
        samples.append(
            DatasetSample(
                asset_id=str(asset["id"]),
                sha256=str(asset["sha256"]),
                object_key=str(asset["object_key"]),
                filename=str(asset["original_filename"]),
                label=str(metadata.get("label", "unlabeled")),
                source_key=str(asset.get("source_id")) if asset.get("source_id") else None,
                group_key=str(asset["sha256"]),
                perceptual_hash=(
                    str(analysis["perceptual_hash"]) if analysis.get("perceptual_hash") else None
                ),
            )
        )
    return samples


def _tabular_query(payload: TabularQueryRequest) -> TabularQuery:
    return TabularQuery(
        filters=tuple(
            TabularFilter(item.column, item.operator, item.value) for item in payload.filters
        ),
        search=payload.search,
        sort_by=payload.sort_by,
        descending=payload.descending,
        visible_columns=tuple(payload.visible_columns),
        limit=payload.limit,
        offset=payload.offset,
    )


def _job_response(job) -> dict[str, object]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "kind": job.kind,
        "state": job.state.value,
        "profile": job.profile.value,
        "processor": {
            "id": job.processor.id,
            "version": job.processor.version,
            "deterministic": job.processor.deterministic,
            "cacheable": job.processor.cacheable,
            "model_revision": job.processor.model_revision,
        },
        "counts": {
            "total": job.total_items,
            "processed": job.processed_count,
            "failed": job.failed_count,
            "skipped": job.skipped_count,
            "cached": job.cached_count,
        },
        "progress": job.progress,
        "checkpoint": job.checkpoint,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


# Additive 2.0 routes delegate business logic to the shared operation SDK.
from .lab import router as lab_router

app.include_router(lab_router)

from .multimodal import router as multimodal_router

app.include_router(multimodal_router)

from .integrations import router as integrations_router

app.include_router(integrations_router)
