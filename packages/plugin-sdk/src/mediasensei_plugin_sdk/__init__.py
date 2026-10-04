from __future__ import annotations

import json
import math
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

PLUGIN_API_VERSION = "1.5"
PLUGIN_ENTRY_POINT_GROUP = "mediasensei.plugins"
CAPABILITIES = frozenset(
    {
        "analyzer",
        "ocr_provider",
        "embedding_provider",
        "vector_store_provider",
        "dataset_provider",
        "discovery_provider",
        "acquisition_downloader",
        "prompt_planner",
        "relevance_evaluator",
        "exporter",
    }
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,119}$")
_PERMISSION = re.compile(r"^[a-z][a-z0-9_.:-]{1,119}$")
MAX_PAGE_CANDIDATES = 500
MAX_RECORD_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 8_192


def _bounded_text(value: str | None, field_name: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise PluginValidationError(f"{field_name} is required")
        return
    if required and not value.strip():
        raise PluginValidationError(f"{field_name} is required")
    if len(value) > MAX_TEXT_LENGTH:
        raise PluginValidationError(f"{field_name} exceeds the 8192 character limit")


def _web_url(value: str | None, field_name: str, *, required: bool = False) -> None:
    _bounded_text(value, field_name, required=required)
    if value is None:
        return
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise PluginValidationError(f"{field_name} must be an HTTP(S) URL without credentials")


def _json_size(value: object, field_name: str) -> None:
    try:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PluginValidationError(f"{field_name} must be finite JSON data") from error
    if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
        raise PluginValidationError(f"{field_name} exceeds the 64 KiB record limit")


class PluginValidationError(ValueError):
    """A safe, user-facing plugin contract validation error."""


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    api: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...] = ()
    license: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        if not _SLUG.fullmatch(name):
            raise PluginValidationError(
                "Plugin names must be stable lowercase slugs containing 2 to 120 characters"
            )
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise PluginValidationError("Plugin version must be a valid PEP 440 version") from error
        try:
            supported = SpecifierSet(self.api)
        except InvalidSpecifier as error:
            raise PluginValidationError(
                "Plugin API compatibility is not a valid specifier"
            ) from error
        if Version(PLUGIN_API_VERSION) not in supported:
            raise PluginValidationError(
                f"Plugin does not support MediaSensei Plugin API {PLUGIN_API_VERSION}"
            )
        capabilities = tuple(dict.fromkeys(value.strip() for value in self.capabilities))
        unknown = sorted(set(capabilities) - CAPABILITIES)
        if not capabilities or unknown:
            detail = f": {', '.join(unknown)}" if unknown else ""
            raise PluginValidationError(f"Plugin capabilities are missing or unknown{detail}")
        permissions = tuple(dict.fromkeys(value.strip() for value in self.permissions))
        if any(not _PERMISSION.fullmatch(value) for value in permissions):
            raise PluginValidationError("Plugin permissions must use stable lowercase identifiers")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "permissions", permissions)


@dataclass(frozen=True, slots=True)
class OCRRegion:
    text: str
    confidence: float | None = None
    bounds: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float | None
    regions: tuple[OCRRegion, ...]
    language: str | None
    provider: str
    provider_version: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    query: str
    modality: str = "image"
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not self.query.strip() or not 1 <= self.limit <= 500:
            raise PluginValidationError(
                "Discovery requests require a query and limit from 1 to 500"
            )


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    provider_id: str
    remote_id: str
    source_url: str
    modality: str = "image"
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
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _SLUG.fullmatch(self.provider_id.strip().lower()):
            raise PluginValidationError("Discovery candidates require a stable provider id")
        _bounded_text(self.remote_id, "remote_id", required=True)
        _web_url(self.source_url, "source_url", required=True)
        _web_url(self.landing_page_url, "landing_page_url")
        _web_url(self.preview_url, "preview_url")
        for name, value in (
            ("title", self.title),
            ("description", self.description),
            ("author", self.author),
            ("license", self.license),
        ):
            _bounded_text(value, name)
        numeric_values: tuple[tuple[str, int | None], ...] = (
            ("width", self.width),
            ("height", self.height),
            ("estimated_size", self.estimated_size),
        )
        for numeric_name, numeric_value in numeric_values:
            if numeric_value is not None and numeric_value < 0:
                raise PluginValidationError(f"{numeric_name} cannot be negative")
        _json_size(dict(self.metadata), "metadata")


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    candidates: tuple[DiscoveryCandidate, ...]
    next_cursor: str | None = None
    elapsed_ms: float | None = None

    def __post_init__(self) -> None:
        if len(self.candidates) > MAX_PAGE_CANDIDATES:
            raise PluginValidationError("Discovery pages cannot contain more than 500 candidates")
        identities = {(item.provider_id, item.remote_id) for item in self.candidates}
        if len(identities) != len(self.candidates):
            raise PluginValidationError(
                "Discovery pages cannot contain duplicate candidate identities"
            )
        _bounded_text(self.next_cursor, "next_cursor")
        if self.elapsed_ms is not None and (
            not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0
        ):
            raise PluginValidationError("elapsed_ms must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    final_url: str
    content_type: str
    byte_size: int

    def __post_init__(self) -> None:
        _web_url(self.final_url, "final_url", required=True)
        _bounded_text(self.content_type, "content_type", required=True)
        if self.byte_size < 0:
            raise PluginValidationError("byte_size cannot be negative")


@dataclass(frozen=True, slots=True)
class AcquisitionTarget:
    unit: str = "accepted_assets"
    count: int = 100

    def __post_init__(self) -> None:
        if self.unit not in {"accepted_assets"} or not 1 <= self.count <= 100_000:
            raise PluginValidationError("Acquisition targets require 1 to 100000 accepted assets")


@dataclass(frozen=True, slots=True)
class AcquisitionBudget:
    max_candidates: int = 1_500
    max_download_bytes: int = 25 * 1024**3
    max_storage_bytes: int = 20 * 1024**3
    max_requests: int = 2_000
    max_external_cost: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.max_candidates,
            self.max_download_bytes,
            self.max_storage_bytes,
            self.max_requests,
        )
        if any(value <= 0 for value in values):
            raise PluginValidationError("Acquisition budget limits must be positive")
        if self.max_external_cost is not None and (
            not math.isfinite(self.max_external_cost) or self.max_external_cost < 0
        ):
            raise PluginValidationError("max_external_cost must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class AcquisitionSpec:
    modality: str
    topic: str
    target: AcquisitionTarget = field(default_factory=AcquisitionTarget)
    categories: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    provider_ids: tuple[str, ...] = ("wikimedia-commons", "openverse")
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

    def __post_init__(self) -> None:
        if self.modality not in {"image", "video", "audio", "document", "tabular"}:
            raise PluginValidationError("Acquisition modality is not supported")
        _bounded_text(self.topic, "topic", required=True)
        if not 1 <= self.min_width <= 100_000 or not 1 <= self.min_height <= 100_000:
            raise PluginValidationError("Minimum dimensions must be from 1 to 100000")
        if not math.isfinite(self.min_quality) or self.min_quality < 0:
            raise PluginValidationError("Minimum quality must be finite and non-negative")
        if not 0 <= self.near_duplicate_threshold <= 64:
            raise PluginValidationError("Near-duplicate threshold must be from 0 to 64")
        for collection_name, values in (
            ("categories", self.categories),
            ("queries", self.queries),
            ("provider_ids", self.provider_ids),
        ):
            if len(values) > 100:
                raise PluginValidationError(
                    f"{collection_name} cannot contain more than 100 values"
                )
            for value in values:
                _bounded_text(value, collection_name, required=True)

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AcquisitionDecision:
    decision: str
    reason: str
    evaluator_id: str
    evaluator_version: str
    scores: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in {"accept", "reject", "review"}:
            raise PluginValidationError("Acquisition decisions must be accept, reject, or review")
        for name, value in (
            ("reason", self.reason),
            ("evaluator_id", self.evaluator_id),
            ("evaluator_version", self.evaluator_version),
        ):
            _bounded_text(value, name, required=True)
        _json_size(dict(self.scores), "scores")


@runtime_checkable
class Analyzer(Protocol):
    manifest: PluginManifest

    def analyze(self, object_key: str, parameters: dict[str, object]) -> dict[str, object]: ...


@runtime_checkable
class OCRProvider(Protocol):
    provider_id: str
    version: str | None

    def available(self) -> bool: ...

    def recognize(self, image_path: Path, *, language: str | None = None) -> OCRResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_id: str
    model_revision: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]: ...


@runtime_checkable
class VectorStoreProvider(Protocol):
    provider_id: str

    def search(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 5,
        minimum_score: float = 0.0,
        asset_ids: list[str] | None = None,
    ) -> list[object]: ...


@runtime_checkable
class DatasetProvider(Protocol):
    provider_id: str
    version: str

    def available(self) -> bool: ...

    def resolve(self, dataset_id: str, revision: str | None = None) -> Any: ...

    def download_file(
        self,
        snapshot: Any,
        file: Any,
        destination: Path,
        *,
        max_bytes: int,
    ) -> None: ...


@runtime_checkable
class DiscoveryProvider(Protocol):
    provider_id: str
    version: str

    def available(self) -> bool: ...

    def capabilities(self) -> Mapping[str, object]: ...

    def search(self, request: DiscoveryRequest) -> DiscoveryPage: ...


@runtime_checkable
class AcquisitionDownloader(Protocol):
    downloader_id: str
    version: str

    def download(
        self,
        url: str,
        destination: Path,
        *,
        max_bytes: int,
    ) -> DownloadReceipt: ...


@runtime_checkable
class PromptPlannerProvider(Protocol):
    planner_id: str
    version: str

    def plan(self, prompt: str) -> AcquisitionSpec: ...


@runtime_checkable
class RelevanceEvaluator(Protocol):
    evaluator_id: str
    version: str

    def evaluate(
        self,
        spec: AcquisitionSpec,
        candidate: DiscoveryCandidate,
    ) -> AcquisitionDecision: ...


@runtime_checkable
class Exporter(Protocol):
    exporter_id: str

    def export(self, records: list[dict[str, object]], destination: Path) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    manifest: PluginManifest
    analyzers: tuple[Analyzer, ...] = ()
    ocr_providers: tuple[OCRProvider, ...] = ()
    embedding_providers: tuple[EmbeddingProvider, ...] = ()
    vector_store_providers: tuple[VectorStoreProvider, ...] = ()
    dataset_providers: tuple[DatasetProvider, ...] = ()
    discovery_providers: tuple[DiscoveryProvider, ...] = ()
    acquisition_downloaders: tuple[AcquisitionDownloader, ...] = ()
    prompt_planners: tuple[PromptPlannerProvider, ...] = ()
    relevance_evaluators: tuple[RelevanceEvaluator, ...] = ()
    exporters: tuple[Exporter, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    entry_point: str
    status: str
    code: str
    message: str
    plugin_name: str | None = None
    plugin_version: str | None = None
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PluginDiscoveryReport:
    plugins: tuple[PluginRegistration, ...]
    diagnostics: tuple[PluginDiagnostic, ...]

    @property
    def healthy(self) -> bool:
        return all(item.status == "loaded" for item in self.diagnostics)

    def to_dict(self) -> dict[str, object]:
        return {
            "api_version": PLUGIN_API_VERSION,
            "healthy": self.healthy,
            "plugins": [
                {
                    "name": item.manifest.name,
                    "version": item.manifest.version,
                    "api": item.manifest.api,
                    "capabilities": list(item.manifest.capabilities),
                    "permissions": list(item.manifest.permissions),
                    "license": item.manifest.license,
                }
                for item in self.plugins
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def validate_registration(registration: PluginRegistration) -> PluginRegistration:
    groups: dict[str, tuple[object, ...]] = {
        "analyzer": registration.analyzers,
        "ocr_provider": registration.ocr_providers,
        "embedding_provider": registration.embedding_providers,
        "vector_store_provider": registration.vector_store_providers,
        "dataset_provider": registration.dataset_providers,
        "discovery_provider": registration.discovery_providers,
        "acquisition_downloader": registration.acquisition_downloaders,
        "prompt_planner": registration.prompt_planners,
        "relevance_evaluator": registration.relevance_evaluators,
        "exporter": registration.exporters,
    }
    provided = {name for name, values in groups.items() if values}
    declared = set(registration.manifest.capabilities)
    if provided != declared:
        missing = sorted(declared - provided)
        undeclared = sorted(provided - declared)
        detail = []
        if missing:
            detail.append(f"missing implementations: {', '.join(missing)}")
        if undeclared:
            detail.append(f"undeclared implementations: {', '.join(undeclared)}")
        raise PluginValidationError("Manifest capability mismatch (" + "; ".join(detail) + ")")
    protocols: dict[str, type[object]] = {
        "analyzer": Analyzer,
        "ocr_provider": OCRProvider,
        "embedding_provider": EmbeddingProvider,
        "vector_store_provider": VectorStoreProvider,
        "dataset_provider": DatasetProvider,
        "discovery_provider": DiscoveryProvider,
        "acquisition_downloader": AcquisitionDownloader,
        "prompt_planner": PromptPlannerProvider,
        "relevance_evaluator": RelevanceEvaluator,
        "exporter": Exporter,
    }
    for capability, values in groups.items():
        if len(values) > 64:
            raise PluginValidationError(f"{capability} cannot register more than 64 components")
        identities: set[str] = set()
        for value in values:
            if not isinstance(value, protocols[capability]):
                raise PluginValidationError(
                    f"{capability} does not implement the finalized structural contract"
                )
            identity = _capability_identity(capability, value)
            if not _SLUG.fullmatch(identity):
                raise PluginValidationError(f"{capability} has an invalid stable identifier")
            if identity in identities:
                raise PluginValidationError(f"Duplicate {capability} identifier: {identity}")
            identities.add(identity)
    return registration


def validate_plugin_object(value: object) -> PluginRegistration:
    """Validate an already loaded entry-point object without discovering the environment."""
    return validate_registration(_coerce_registration(value))


def inspect_plugins(entries: Iterable[object] | None = None) -> PluginDiscoveryReport:
    selected = (
        list(entries) if entries is not None else list(entry_points(group=PLUGIN_ENTRY_POINT_GROUP))
    )
    plugins: list[PluginRegistration] = []
    diagnostics: list[PluginDiagnostic] = []
    names: set[str] = set()
    for entry in sorted(selected, key=lambda item: str(getattr(item, "name", ""))):
        entry_name = str(getattr(entry, "name", "unknown"))
        try:
            loaded = entry.load()  # type: ignore[attr-defined]
            registration = _coerce_registration(loaded)
            validate_registration(registration)
            manifest = registration.manifest
            if manifest.name in names:
                raise PluginValidationError(f"Duplicate plugin name: {manifest.name}")
            names.add(manifest.name)
            plugins.append(registration)
            diagnostics.append(
                PluginDiagnostic(
                    entry_name,
                    "loaded",
                    "PLUGIN_LOADED",
                    "Plugin loaded and passed compatibility validation",
                    manifest.name,
                    manifest.version,
                    manifest.capabilities,
                )
            )
        except PluginValidationError as error:
            diagnostics.append(
                PluginDiagnostic(entry_name, "rejected", "PLUGIN_INVALID", str(error))
            )
        except Exception as error:  # noqa: BLE001 - third-party import isolation
            diagnostics.append(
                PluginDiagnostic(
                    entry_name,
                    "failed",
                    "PLUGIN_LOAD_FAILED",
                    f"Plugin import failed safely ({type(error).__name__})",
                )
            )
    return PluginDiscoveryReport(tuple(plugins), tuple(diagnostics))


def discover_plugins() -> dict[str, PluginRegistration]:
    """Load only compatible plugins; inspect_plugins exposes rejected diagnostics."""
    return {item.manifest.name: item for item in inspect_plugins().plugins}


def _coerce_registration(value: object) -> PluginRegistration:
    if isinstance(value, PluginRegistration):
        return value
    registration = getattr(value, "registration", None)
    if isinstance(registration, PluginRegistration):
        return registration
    raise PluginValidationError("Entry point must expose a PluginRegistration")


def _capability_identity(capability: str, value: object) -> str:
    attribute = {
        "analyzer": "manifest",
        "ocr_provider": "provider_id",
        "embedding_provider": "provider_id",
        "vector_store_provider": "provider_id",
        "dataset_provider": "provider_id",
        "discovery_provider": "provider_id",
        "acquisition_downloader": "downloader_id",
        "prompt_planner": "planner_id",
        "relevance_evaluator": "evaluator_id",
        "exporter": "exporter_id",
    }[capability]
    identity = getattr(value, attribute, None)
    if capability == "analyzer" and isinstance(identity, PluginManifest):
        identity = identity.name
    return str(identity or "").strip().lower()
