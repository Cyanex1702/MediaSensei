from __future__ import annotations

import fnmatch
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from mediasensei_plugin_sdk import DatasetProvider  # type: ignore[import-untyped]

from mediasensei.domain.jobs import ProcessorSpec, ResourceHints, ResourceLevel, WorkItem
from mediasensei.domain.providers import (
    DatasetSnapshot,
    ProviderFile,
    ProviderImportOptions,
    ProviderImportResult,
    ProviderImportState,
)
from mediasensei.infrastructure.storage import ContentAddressedStore

if TYPE_CHECKING:
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.worker import ProcessorRegistry


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderImportError(RuntimeError):
    pass


class _DatasetInfoClient(Protocol):
    def dataset_info(self, repo_id: str, **kwargs: object) -> object: ...


class _KaggleClient(Protocol):
    def authenticate(self) -> None: ...

    def dataset_view(self, dataset_id: str, **kwargs: object) -> object: ...

    def dataset_files_list(self, dataset_id: str, **kwargs: object) -> object: ...

    def dataset_download_file(
        self, dataset_id: str, file_name: str, **kwargs: object
    ) -> object: ...


class DatasetProviderRegistry:
    def __init__(self, providers: Iterable[DatasetProvider] = ()) -> None:
        self._providers: dict[str, DatasetProvider] = {}
        for provider in providers:
            self.register(provider)

    @classmethod
    def defaults(cls) -> DatasetProviderRegistry:
        return cls((HuggingFaceDatasetProvider(), KaggleDatasetProvider()))

    def register(self, provider: DatasetProvider) -> None:
        provider_id = provider.provider_id.strip().lower()
        if not provider_id:
            raise ValueError("Dataset providers require a stable provider id")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> DatasetProvider:
        try:
            return self._providers[provider_id.strip().lower()]
        except KeyError as error:
            raise LookupError(f"Dataset provider is not installed: {provider_id}") from error

    def capabilities(self) -> list[dict[str, object]]:
        return [
            {
                "id": provider.provider_id,
                "version": provider.version,
                "available": provider.available(),
                "supports_revisions": True,
                "requires_network": True,
            }
            for provider in sorted(self._providers.values(), key=lambda item: item.provider_id)
        ]


class HuggingFaceDatasetProvider:
    provider_id = "huggingface"

    def __init__(
        self,
        *,
        client: _DatasetInfoClient | None = None,
        downloader: Callable[..., str] | None = None,
        token: str | None = None,
    ) -> None:
        self._client = client
        self._downloader = downloader
        self._token = token
        self.version = _package_version("huggingface_hub", "unavailable")
        if client is not None and self.version == "unavailable":
            self.version = "test-adapter"

    def available(self) -> bool:
        return self._client is not None or importlib.util.find_spec("huggingface_hub") is not None

    def _runtime(self) -> tuple[_DatasetInfoClient, Callable[..., str], str | None]:
        token = (
            self._token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )
        if self._client is not None and self._downloader is not None:
            return self._client, self._downloader, token
        try:
            module = importlib.import_module("huggingface_hub")
        except ImportError as error:
            raise ProviderUnavailableError(
                "Hugging Face imports require: pip install 'mediasensei[providers]'"
            ) from error
        runtime = cast(Any, module)
        client = self._client or runtime.HfApi(token=token)
        downloader = self._downloader or runtime.hf_hub_download
        self.version = _package_version("huggingface_hub", self.version)
        return cast(_DatasetInfoClient, client), cast(Callable[..., str], downloader), token

    def resolve(self, dataset_id: str, revision: str | None = None) -> DatasetSnapshot:
        clean_id = _validate_dataset_id(dataset_id)
        client, _, _ = self._runtime()
        info = client.dataset_info(clean_id, revision=revision, files_metadata=True)
        resolved = str(_field(info, "sha") or "").strip()
        if not resolved:
            raise ProviderImportError("Hugging Face did not return a resolved commit revision")
        siblings = _field(info, "siblings") or ()
        files: list[ProviderFile] = []
        for sibling in cast(Iterable[object], siblings):
            path = str(_field(sibling, "rfilename", "path") or "").strip()
            if not path:
                continue
            lfs = _field(sibling, "lfs")
            sha256 = _field(lfs, "sha256") if lfs else None
            files.append(
                ProviderFile(
                    path=path,
                    byte_size=_optional_int(_field(sibling, "size")),
                    sha256=str(sha256).lower() if sha256 else None,
                    etag=str(_field(sibling, "blob_id", "blobId") or "") or None,
                )
            )
        card_data = _field(info, "card_data", "cardData")
        license_value = _field(card_data, "license") if card_data else None
        return DatasetSnapshot(
            provider_id=self.provider_id,
            provider_version=self.version,
            dataset_id=clean_id,
            requested_revision=revision,
            resolved_revision=resolved,
            source_uri=f"https://huggingface.co/datasets/{clean_id}",
            title=str(_field(info, "id") or clean_id),
            license=_license_text(license_value),
            files=tuple(sorted(files, key=lambda item: item.path)),
            metadata={
                "private": bool(_field(info, "private") or False),
                "gated": bool(_field(info, "gated") or False),
            },
        )

    def download_file(
        self,
        snapshot: DatasetSnapshot,
        file: ProviderFile,
        destination: Path,
        *,
        max_bytes: int,
    ) -> None:
        _, downloader, token = self._runtime()
        if file.byte_size is not None and file.byte_size > max_bytes:
            raise ProviderImportError(f"Provider file exceeds the byte limit: {file.path}")
        cached = Path(
            downloader(
                repo_id=snapshot.dataset_id,
                filename=file.path,
                repo_type="dataset",
                revision=snapshot.resolved_revision,
                token=token,
            )
        ).resolve(strict=True)
        _copy_bounded(cached, destination, max_bytes)


class KaggleDatasetProvider:
    provider_id = "kaggle"

    def __init__(self, *, client: _KaggleClient | None = None) -> None:
        self._client = client
        self._authenticated = client is not None
        self.version = _package_version("kaggle", "unavailable")
        if client is not None and self.version == "unavailable":
            self.version = "test-adapter"

    def available(self) -> bool:
        return self._client is not None or importlib.util.find_spec("kaggle") is not None

    def _runtime(self) -> _KaggleClient:
        if self._client is None:
            try:
                module = importlib.import_module("kaggle.api.kaggle_api_extended")
            except ImportError as error:
                raise ProviderUnavailableError(
                    "Kaggle imports require: pip install 'mediasensei[providers]'"
                ) from error
            self._client = cast(_KaggleClient, cast(Any, module).KaggleApi())
            self.version = _package_version("kaggle", self.version)
        if not self._authenticated:
            authenticate = getattr(self._client, "authenticate", None)
            if callable(authenticate):
                authenticate()
            self._authenticated = True
        return self._client

    def resolve(self, dataset_id: str, revision: str | None = None) -> DatasetSnapshot:
        clean_id = _validate_dataset_id(dataset_id)
        client = self._runtime()
        view_method = client.dataset_view
        view_kwargs = _supported_kwargs(
            view_method,
            {"dataset_version_number": int(revision) if revision else None},
        )
        view = view_method(clean_id, **view_kwargs)
        current_revision = str(
            _field(view, "current_version_number", "currentVersionNumber", "version_number") or ""
        ).strip()
        resolved = revision or current_revision
        if not resolved:
            raise ProviderImportError("Kaggle did not return a resolved dataset version")
        if revision and current_revision and revision != current_revision and not view_kwargs:
            raise ProviderImportError(
                "This Kaggle client cannot resolve historical versions; update the provider client"
            )

        files: list[ProviderFile] = []
        page_token: str | None = None
        while True:
            file_method = client.dataset_files_list
            response = file_method(
                clean_id,
                **_supported_kwargs(
                    file_method,
                    {
                        "page_token": page_token,
                        "page_size": 200,
                        "dataset_version_number": int(resolved),
                    },
                ),
            )
            values = _field(response, "dataset_files", "datasetFiles", "files") or ()
            for value in cast(Iterable[object], values):
                path = str(_field(value, "name", "path") or "").strip()
                if path:
                    files.append(
                        ProviderFile(
                            path=path,
                            byte_size=_optional_int(
                                _field(value, "total_bytes", "totalBytes", "size")
                            ),
                            etag=str(_field(value, "ref", "etag") or "") or None,
                        )
                    )
            next_token = _field(response, "next_page_token", "nextPageToken")
            if not next_token or str(next_token) == page_token:
                break
            page_token = str(next_token)
        licenses = _field(view, "licenses") or ()
        return DatasetSnapshot(
            provider_id=self.provider_id,
            provider_version=self.version,
            dataset_id=clean_id,
            requested_revision=revision,
            resolved_revision=resolved,
            source_uri=str(_field(view, "url") or f"https://www.kaggle.com/datasets/{clean_id}"),
            title=str(_field(view, "title") or clean_id),
            license=_license_text(licenses),
            files=tuple(sorted(files, key=lambda item: item.path)),
            metadata={
                "owner": clean_id.split("/", 1)[0],
                "is_private": bool(_field(view, "is_private", "isPrivate") or False),
            },
        )

    def download_file(
        self,
        snapshot: DatasetSnapshot,
        file: ProviderFile,
        destination: Path,
        *,
        max_bytes: int,
    ) -> None:
        if file.byte_size is not None and file.byte_size > max_bytes:
            raise ProviderImportError(f"Provider file exceeds the byte limit: {file.path}")
        client = self._runtime()
        method = client.dataset_download_file
        with tempfile.TemporaryDirectory(prefix="mediasensei-kaggle-") as directory:
            root = Path(directory)
            kwargs = _supported_kwargs(
                method,
                {
                    "path": str(root),
                    "force": True,
                    "quiet": True,
                    "dataset_version_number": int(snapshot.resolved_revision),
                },
            )
            returned = method(snapshot.dataset_id, file.path, **kwargs)
            candidates: list[Path] = []
            if isinstance(returned, (str, os.PathLike)):
                candidates.append(Path(returned))
            candidates.extend((root / file.path, root / Path(file.path).name))
            candidates.extend(root.rglob(Path(file.path).name))
            source = next((candidate for candidate in candidates if candidate.is_file()), None)
            if source is None:
                raise ProviderImportError(f"Kaggle did not materialize requested file: {file.path}")
            resolved_root = root.resolve()
            resolved_source = source.resolve(strict=True)
            if not resolved_source.is_relative_to(resolved_root):
                raise ProviderImportError("Kaggle materialized a file outside the download root")
            _copy_bounded(resolved_source, destination, max_bytes)
        latest = self.resolve(snapshot.dataset_id)
        if latest.resolved_revision != snapshot.resolved_revision:
            raise ProviderImportError(
                "Kaggle dataset revision changed during download; retry the import"
            )


class ProviderImportService:
    def __init__(
        self,
        catalog: Catalog,
        *,
        registry: DatasetProviderRegistry | None = None,
        store: ContentAddressedStore | None = None,
        sensitive_values: tuple[str, ...] = (),
        control_check: Callable[[], None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.registry = registry or DatasetProviderRegistry.defaults()
        self.store = store or ContentAddressedStore(catalog.workspace)
        self.sensitive_values = sensitive_values
        self.control_check = control_check

    def execute(self, import_id: str) -> ProviderImportResult:
        record = self.catalog.provider_import(import_id)
        provider = self.registry.get(str(record["provider_id"]))
        options = ProviderImportOptions(
            allow_patterns=tuple(cast(list[str], record["allow_patterns"])),
            ignore_patterns=tuple(cast(list[str], record["ignore_patterns"])),
            max_files=int(cast(Any, record["max_files"])),
            max_file_bytes=int(cast(Any, record["max_file_bytes"])),
            max_total_bytes=int(cast(Any, record["max_total_bytes"])),
        )
        self.catalog.set_provider_import_state(import_id, ProviderImportState.RESOLVING.value)
        try:
            if self.control_check:
                self.control_check()
            snapshot = provider.resolve(
                str(record["dataset_id"]),
                str(record["requested_revision"]) if record.get("requested_revision") else None,
            )
            selected, filtered_count = _select_files(snapshot.files, options)
            known_bytes = sum(item.byte_size or 0 for item in selected)
            if known_bytes > options.max_total_bytes:
                raise ProviderImportError(
                    "Resolved provider files exceed the configured total byte limit"
                )
            manifest_hash = _manifest_hash(snapshot, selected, options)
            source_id = self.catalog.resolve_provider_import(
                import_id,
                snapshot=snapshot,
                files=selected,
                manifest_hash=manifest_hash,
                filtered_count=filtered_count,
            )
            self.catalog.set_provider_import_state(import_id, ProviderImportState.IMPORTING.value)
        except Exception as error:
            self.catalog.set_provider_import_state(
                import_id, ProviderImportState.FAILED.value, _safe_provider_error(error, self.sensitive_values)
            )
            raise

        failures: list[str] = []
        imported_bytes = int(cast(Any, record.get("imported_bytes") or 0))
        for item in self.catalog.provider_import_files(import_id, incomplete_only=True):
            relative_path = str(item["relative_path"])
            provider_file = ProviderFile(
                path=relative_path,
                byte_size=(
                    int(cast(Any, item["byte_size"])) if item.get("byte_size") is not None else None
                ),
                sha256=str(item["expected_sha256"]) if item.get("expected_sha256") else None,
                etag=str(item["etag"]) if item.get("etag") else None,
                metadata=cast(dict[str, Any], item.get("metadata") or {}),
            )
            if provider_file.byte_size is not None and (
                imported_bytes + provider_file.byte_size > options.max_total_bytes
            ):
                self.catalog.skip_provider_import_file(import_id, relative_path, "total_byte_limit")
                continue
            self.catalog.start_provider_import_file(import_id, relative_path)
            fd, temporary_name = tempfile.mkstemp(prefix="provider-", dir=self.store.temp_root)
            os.close(fd)
            temporary = Path(temporary_name)
            try:
                if self.control_check:
                    self.control_check()
                provider.download_file(
                    snapshot,
                    provider_file,
                    temporary,
                    max_bytes=options.max_file_bytes,
                )
                actual_size = temporary.stat().st_size
                if imported_bytes + actual_size > options.max_total_bytes:
                    self.catalog.skip_provider_import_file(
                        import_id, relative_path, "total_byte_limit"
                    )
                    continue
                stored = self.store.import_file(temporary)
                if provider_file.sha256 and provider_file.sha256 != stored.sha256:
                    raise ProviderImportError(
                        f"Provider checksum mismatch for {provider_file.path}"
                    )
                asset_id = self.catalog.record_asset(
                    project_id=str(record["project_id"]),
                    source_id=source_id,
                    sha256=stored.sha256,
                    original_filename=Path(provider_file.path).name,
                    media_type=_media_type(provider_file.path),
                    object_key=stored.object_key,
                    byte_size=stored.byte_size,
                    metadata={
                        "provider_id": snapshot.provider_id,
                        "provider_version": snapshot.provider_version,
                        "dataset_id": snapshot.dataset_id,
                        "requested_revision": snapshot.requested_revision,
                        "resolved_revision": snapshot.resolved_revision,
                        "provider_path": provider_file.path,
                        "source_uri": snapshot.source_uri,
                        "license": snapshot.license,
                    },
                )
                self.catalog.complete_provider_import_file(
                    import_id,
                    relative_path,
                    asset_id=asset_id,
                    actual_sha256=stored.sha256,
                    object_key=stored.object_key,
                    byte_size=stored.byte_size,
                )
                imported_bytes += stored.byte_size
            except Exception as error:  # noqa: BLE001 - isolate provider file failures
                failures.append(relative_path)
                self.catalog.fail_provider_import_file(
                    import_id, relative_path, _safe_provider_error(error, self.sensitive_values)
                )
            finally:
                temporary.unlink(missing_ok=True)

        summary = self.catalog.provider_import_file_counts(import_id)
        final_state = (
            ProviderImportState.COMPLETED_WITH_ERRORS
            if summary["failed"]
            else ProviderImportState.COMPLETED
        )
        self.catalog.finalize_provider_import(import_id, final_state.value, manifest_hash)
        if failures:
            message = f"{len(failures)} provider file(s) failed; retry the failed job item"
            self.catalog.set_provider_import_state(import_id, final_state.value, message)
            raise ProviderImportError(message)
        return ProviderImportResult(
            import_id=import_id,
            provider_id=snapshot.provider_id,
            dataset_id=snapshot.dataset_id,
            resolved_revision=snapshot.resolved_revision,
            imported_files=summary["completed"],
            skipped_files=summary["skipped"],
            failed_files=summary["failed"],
            imported_bytes=summary["imported_bytes"],
            manifest_hash=manifest_hash,
        )


def register_provider_processors(
    registry: ProcessorRegistry,
    catalog: Catalog,
    *,
    providers: DatasetProviderRegistry | None = None,
) -> None:
    service = ProviderImportService(catalog, registry=providers)

    def import_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        import_id = str(parameters.get("import_id") or item.input_ref)
        if not import_id:
            raise ValueError("Provider import jobs require an import id")
        result = service.execute(import_id)
        return {
            "import_id": result.import_id,
            "provider_id": result.provider_id,
            "dataset_id": result.dataset_id,
            "resolved_revision": result.resolved_revision,
            "imported_files": result.imported_files,
            "skipped_files": result.skipped_files,
            "imported_bytes": result.imported_bytes,
            "manifest_hash": result.manifest_hash,
        }

    registry.register("dataset-provider.import", import_processor)


def provider_processor_spec() -> ProcessorSpec:
    return ProcessorSpec(
        id="dataset-provider.import",
        version="1.0.0",
        deterministic=False,
        cacheable=False,
        resource_hints=ResourceHints(
            cpu=ResourceLevel.LOW,
            memory=ResourceLevel.LOW,
            disk=ResourceLevel.HIGH,
            network=ResourceLevel.HIGH,
        ),
    )


def provider_request_hash(
    provider_id: str,
    dataset_id: str,
    revision: str | None,
    options: ProviderImportOptions,
) -> str:
    payload = {
        "provider_id": provider_id,
        "dataset_id": dataset_id,
        "revision": revision,
        "allow_patterns": options.allow_patterns,
        "ignore_patterns": options.ignore_patterns,
        "max_files": options.max_files,
        "max_file_bytes": options.max_file_bytes,
        "max_total_bytes": options.max_total_bytes,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _select_files(
    files: tuple[ProviderFile, ...], options: ProviderImportOptions
) -> tuple[tuple[ProviderFile, ...], int]:
    selected: list[ProviderFile] = []
    filtered = 0
    for item in files:
        allowed = not options.allow_patterns or any(
            fnmatch.fnmatchcase(item.path, pattern) for pattern in options.allow_patterns
        )
        ignored = any(
            fnmatch.fnmatchcase(item.path, pattern) for pattern in options.ignore_patterns
        )
        oversized = item.byte_size is not None and item.byte_size > options.max_file_bytes
        if not allowed or ignored or oversized or len(selected) >= options.max_files:
            filtered += 1
            continue
        selected.append(item)
    if not selected:
        raise ProviderImportError("No provider files matched the import limits and patterns")
    return tuple(selected), filtered


def _manifest_hash(
    snapshot: DatasetSnapshot,
    files: tuple[ProviderFile, ...],
    options: ProviderImportOptions,
) -> str:
    payload = {
        "provider_id": snapshot.provider_id,
        "provider_version": snapshot.provider_version,
        "dataset_id": snapshot.dataset_id,
        "requested_revision": snapshot.requested_revision,
        "resolved_revision": snapshot.resolved_revision,
        "source_uri": snapshot.source_uri,
        "license": snapshot.license,
        "files": [
            {
                "path": item.path,
                "byte_size": item.byte_size,
                "sha256": item.sha256,
                "etag": item.etag,
            }
            for item in files
        ],
        "options": {
            "allow_patterns": options.allow_patterns,
            "ignore_patterns": options.ignore_patterns,
            "max_files": options.max_files,
            "max_file_bytes": options.max_file_bytes,
            "max_total_bytes": options.max_total_bytes,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _safe_provider_error(error: Exception, sensitive_values: tuple[str, ...] = ()) -> str:
    message = str(error) or error.__class__.__name__
    for secret in sensitive_values:
        if secret:
            message = message.replace(secret, "[redacted]")
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "KAGGLE_KEY"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(
        r"(?i)(authorization|token|api[_-]?key)(\s*[=:]\s*)([^\s&,;]+)",
        r"\1\2[redacted]",
        message,
    )
    return message[:2000]


def _validate_dataset_id(value: str) -> str:
    clean = value.strip().strip("/")
    parts = clean.split("/")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if len(parts) != 2 or any(
        not part or any(char not in allowed for char in part) for part in parts
    ):
        raise ValueError("Dataset ids must use the form owner/dataset with safe characters")
    return clean


def _field(value: object, *names: str) -> object | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _optional_int(value: object | None) -> int | None:
    if value is None or value == "":
        return None
    return int(cast(Any, value))


def _license_text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (list, tuple)):
        names = [str(_field(item, "name") or item) for item in value]
        return ", ".join(names)[:500] or None
    return str(value)[:500]


def _supported_kwargs(method: object, values: dict[str, object | None]) -> dict[str, object]:
    try:
        parameters = inspect.signature(cast(Callable[..., object], method)).parameters
    except (TypeError, ValueError):
        return {key: value for key, value in values.items() if value is not None}
    accepts_kwargs = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
    return {
        key: value
        for key, value in values.items()
        if value is not None and (accepts_kwargs or key in parameters)
    }


def _copy_bounded(source: Path, destination: Path, max_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with source.open("rb") as reader, destination.open("wb") as writer:
        while chunk := reader.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                raise ProviderImportError(
                    "Provider download exceeded the configured file byte limit"
                )
            writer.write(chunk)


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
        return "video"
    if suffix in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
        return "audio"
    if suffix in {".txt", ".md", ".html", ".htm", ".pdf", ".docx"}:
        return "document"
    if suffix in {
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".parquet",
        ".xlsx",
        ".sqlite",
        ".db",
        ".duckdb",
        ".arrow",
        ".feather",
    }:
        return "tabular"
    return "unknown"


def _package_version(distribution: str, fallback: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return fallback
