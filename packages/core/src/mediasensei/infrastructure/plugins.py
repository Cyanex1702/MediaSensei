from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, cast

from mediasensei_plugin_sdk import (
    AcquisitionBudget as SDKAcquisitionBudget,
)
from mediasensei_plugin_sdk import (
    AcquisitionDecision as SDKAcquisitionDecision,
)
from mediasensei_plugin_sdk import (
    AcquisitionSpec as SDKAcquisitionSpec,
)
from mediasensei_plugin_sdk import (
    AcquisitionTarget as SDKAcquisitionTarget,
)
from mediasensei_plugin_sdk import (
    DiscoveryCandidate as SDKDiscoveryCandidate,
)
from mediasensei_plugin_sdk import (
    DiscoveryPage as SDKDiscoveryPage,
)
from mediasensei_plugin_sdk import (
    DiscoveryRequest as SDKDiscoveryRequest,
)
from mediasensei_plugin_sdk import (
    DownloadReceipt as SDKDownloadReceipt,
)
from mediasensei_plugin_sdk import (
    PluginDiscoveryReport,
    PluginRegistration,
    inspect_plugins,
    validate_plugin_object,
)

from mediasensei.domain.acquisition import (
    AcquisitionDecision,
    AcquisitionDecisionKind,
    AcquisitionReason,
    AcquisitionSpec,
    DiscoveryCandidate,
    DiscoveryPage,
    DiscoveryRequest,
)
from mediasensei.infrastructure.acquisition_discovery import DownloadReceipt

MAX_PLUGIN_INPUT_BYTES = 64 * 1024
MAX_PLUGIN_OUTPUT_BYTES = 1024 * 1024


class PluginExecutionError(RuntimeError):
    """Safe plugin execution failure without third-party details."""


class PluginDiscoveryProviderAdapter:
    def __init__(self, plugin_name: str, provider: Any) -> None:
        self.plugin_name = plugin_name
        self._provider = provider
        self.provider_id = str(provider.provider_id)
        self.version = str(provider.version)

    def available(self) -> bool:
        return bool(self._provider.available())

    def capabilities(self) -> dict[str, Any]:
        values = self._provider.capabilities()
        if not isinstance(values, Mapping):
            raise PluginExecutionError("Plugin returned invalid capability metadata")
        return {**dict(values), "plugin": self.plugin_name, "contract": "plugin-api-1.5"}

    def search(self, request: DiscoveryRequest) -> DiscoveryPage:
        page = self._provider.search(
            SDKDiscoveryRequest(
                query=request.query,
                modality=request.modality.value,
                limit=request.limit,
                cursor=request.cursor,
            )
        )
        if not isinstance(page, SDKDiscoveryPage):
            raise PluginExecutionError("Discovery plugin returned an invalid page")
        return DiscoveryPage(
            tuple(
                DiscoveryCandidate(
                    provider_id=item.provider_id,
                    remote_id=item.remote_id,
                    source_url=item.source_url,
                    landing_page_url=item.landing_page_url,
                    preview_url=item.preview_url,
                    title=item.title,
                    description=item.description,
                    mime_type=item.mime_type,
                    width=item.width,
                    height=item.height,
                    author=item.author,
                    license=item.license,
                    estimated_size=item.estimated_size,
                    metadata=dict(item.metadata),
                )
                for item in page.candidates
            ),
            page.next_cursor,
            page.elapsed_ms or 0.0,
        )


class PluginDownloaderAdapter:
    def __init__(self, plugin_name: str, downloader: Any) -> None:
        self.plugin_name = plugin_name
        self._downloader = downloader
        self.downloader_id = str(downloader.downloader_id)
        self.version = str(downloader.version)

    def download(self, url: str, destination: Path, *, max_bytes: int) -> DownloadReceipt:
        receipt = self._downloader.download(url, destination, max_bytes=max_bytes)
        if not isinstance(receipt, SDKDownloadReceipt):
            raise PluginExecutionError("Downloader plugin returned an invalid receipt")
        return DownloadReceipt(receipt.final_url, receipt.content_type, receipt.byte_size)


class PluginPromptPlannerAdapter:
    def __init__(self, plugin_name: str, planner: Any) -> None:
        self.plugin_name = plugin_name
        self._planner = planner
        self.planner_id = str(planner.planner_id)
        self.version = str(planner.version)

    def plan(self, prompt: str) -> AcquisitionSpec:
        from mediasensei.infrastructure.acquisition_planning import spec_from_dict

        planned = self._planner.plan(prompt)
        if not isinstance(planned, SDKAcquisitionSpec):
            raise PluginExecutionError("Planner plugin returned an invalid acquisition spec")
        return spec_from_dict(cast(dict[str, Any], planned.to_mapping()))


class PluginRelevanceAdapter:
    def __init__(self, plugin_name: str, evaluator: Any) -> None:
        self.plugin_name = plugin_name
        self._evaluator = evaluator
        self.evaluator_id = str(evaluator.evaluator_id)
        self.version = str(evaluator.version)

    def evaluate(self, spec: AcquisitionSpec, candidate: dict[str, Any]) -> AcquisitionDecision:
        result = self._evaluator.evaluate(
            _sdk_spec(spec),
            SDKDiscoveryCandidate(
                provider_id=str(candidate.get("provider_id") or "unknown"),
                remote_id=str(candidate.get("remote_id") or candidate.get("id") or "unknown"),
                source_url=str(candidate.get("source_url") or ""),
                landing_page_url=_optional_string(candidate.get("landing_page_url")),
                preview_url=_optional_string(candidate.get("preview_url")),
                title=_optional_string(candidate.get("title")),
                description=_optional_string(candidate.get("description")),
                mime_type=_optional_string(candidate.get("mime_type")),
                width=_optional_int(candidate.get("declared_width") or candidate.get("width")),
                height=_optional_int(candidate.get("declared_height") or candidate.get("height")),
                author=_optional_string(candidate.get("author")),
                license=_optional_string(candidate.get("license")),
                estimated_size=_optional_int(candidate.get("estimated_size")),
                metadata=cast(dict[str, object], candidate.get("metadata") or {}),
            ),
        )
        if not isinstance(result, SDKAcquisitionDecision):
            raise PluginExecutionError("Relevance plugin returned an invalid decision")
        return AcquisitionDecision(
            AcquisitionDecisionKind(result.decision),
            AcquisitionReason(result.reason),
            result.evaluator_id,
            result.evaluator_version,
            dict(result.scores),
        )


class PluginRuntime:
    def __init__(self, report: PluginDiscoveryReport) -> None:
        self.report = report

    @classmethod
    def discover(cls, entries: Iterable[object] | None = None) -> PluginRuntime:
        return cls(inspect_plugins(entries))

    def registrations(self) -> tuple[PluginRegistration, ...]:
        return self.report.plugins

    def discovery_providers(self) -> tuple[PluginDiscoveryProviderAdapter, ...]:
        return tuple(
            PluginDiscoveryProviderAdapter(registration.manifest.name, provider)
            for registration in self.report.plugins
            for provider in registration.discovery_providers
        )

    def downloaders(self) -> dict[str, PluginDownloaderAdapter]:
        return {
            adapter.downloader_id: adapter
            for registration in self.report.plugins
            for downloader in registration.acquisition_downloaders
            for adapter in (PluginDownloaderAdapter(registration.manifest.name, downloader),)
        }

    def planners(self) -> dict[str, PluginPromptPlannerAdapter]:
        return {
            adapter.planner_id: adapter
            for registration in self.report.plugins
            for planner in registration.prompt_planners
            for adapter in (PluginPromptPlannerAdapter(registration.manifest.name, planner),)
        }

    def relevance_evaluators(self) -> dict[str, PluginRelevanceAdapter]:
        return {
            adapter.evaluator_id: adapter
            for registration in self.report.plugins
            for evaluator in registration.relevance_evaluators
            for adapter in (PluginRelevanceAdapter(registration.manifest.name, evaluator),)
        }

    def inventory(self) -> dict[str, object]:
        report = self.report.to_dict()
        report["capability_counts"] = {
            "discovery_provider": len(self.discovery_providers()),
            "acquisition_downloader": len(self.downloaders()),
            "prompt_planner": len(self.planners()),
            "relevance_evaluator": len(self.relevance_evaluators()),
            "all": sum(len(item.manifest.capabilities) for item in self.report.plugins),
        }
        return report


class PluginRuntimeManager:
    """Thread-safe runtime snapshot with deliberate, observable reloads."""

    def __init__(self, entries: Iterable[object] | None = None) -> None:
        self._entries = entries
        self._lock = RLock()
        self._generation = 1
        self._loaded_at = _now()
        self._runtime = PluginRuntime.discover(entries)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                **self._runtime.inventory(),
                "generation": self._generation,
                "loaded_at": self._loaded_at,
                "reload_policy": "explicit",
            }

    def reload(self) -> dict[str, object]:
        candidate = PluginRuntime.discover(self._entries)
        with self._lock:
            self._runtime = candidate
            self._generation += 1
            self._loaded_at = _now()
            return self.snapshot()


class PluginTrustStore:
    """Local allow-list bound to an exact SHA-256 plugin source fingerprint."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @classmethod
    def default(cls, workspace: Path | None = None) -> PluginTrustStore:
        override = os.environ.get("MEDIASENSEI_PLUGIN_TRUST_STORE")
        root = workspace or Path(os.environ.get("MEDIASENSEI_WORKSPACE", ".mediasensei-workspace"))
        return cls(Path(override) if override else root / "plugin-trust.json")

    def entries(self) -> tuple[dict[str, object], ...]:
        return tuple(sorted(self._load().values(), key=lambda item: str(item["name"])))

    def approve(self, plugin_file: Path) -> dict[str, object]:
        inspected = validate_plugin_file(plugin_file)
        record = {
            "name": inspected["name"],
            "version": inspected["version"],
            "sha256": inspected["sha256"],
            "permissions": inspected["permissions"],
            "approved_at": _now(),
        }
        values = self._load()
        values[str(record["name"])] = record
        self._save(values)
        return record

    def revoke(self, name: str) -> bool:
        values = self._load()
        removed = values.pop(name.strip().lower(), None) is not None
        if removed:
            self._save(values)
        return removed

    def is_trusted(self, inspected: Mapping[str, object]) -> bool:
        record = self._load().get(str(inspected.get("name", "")))
        return bool(
            record
            and record.get("version") == inspected.get("version")
            and record.get("sha256") == inspected.get("sha256")
        )

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            entries = payload.get("plugins", {}) if isinstance(payload, dict) else {}
            if not isinstance(entries, dict):
                return {}
            return {str(key): value for key, value in entries.items() if isinstance(value, dict)}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, values: dict[str, dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "plugins": values}, indent=2, sort_keys=True) + "\n"
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)


class PluginSubprocessExecutor:
    """Run trusted local analyzers outside the API/CLI process."""

    def __init__(self, trust_store: PluginTrustStore, *, timeout_seconds: float = 15.0) -> None:
        self.trust_store = trust_store
        self.timeout_seconds = max(0.1, min(timeout_seconds, 300.0))

    def analyze(
        self,
        plugin_file: Path,
        object_key: str,
        parameters: Mapping[str, object] | None = None,
        *,
        analyzer_index: int = 0,
    ) -> dict[str, object]:
        # Reject untrusted source bytes before importing executable Python code.
        fingerprint = hashlib.sha256(plugin_file.read_bytes()).hexdigest()
        if not any(entry.get("sha256") == fingerprint for entry in self.trust_store.entries()):
            raise PluginExecutionError("Plugin is not trusted or its source fingerprint changed")
        inspected = validate_plugin_file(plugin_file)
        if not self.trust_store.is_trusted(inspected):
            raise PluginExecutionError("Plugin is not trusted or its source fingerprint changed")
        request = {
            "operation": "analyze",
            "plugin_file": str(plugin_file.resolve()),
            "expected_sha256": inspected["sha256"],
            "analyzer_index": analyzer_index,
            "object_key": object_key,
            "parameters": dict(parameters or {}),
        }
        encoded = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_PLUGIN_INPUT_BYTES:
            raise PluginExecutionError("Plugin request exceeds the 64 KiB input limit")
        environment = _isolated_environment()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "mediasensei.infrastructure.plugin_host"],
                input=encoded,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                cwd=tempfile.gettempdir(),
                env=environment,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as error:
            raise PluginExecutionError("Plugin execution timed out") from error
        if len(completed.stdout.encode("utf-8")) > MAX_PLUGIN_OUTPUT_BYTES:
            raise PluginExecutionError("Plugin output exceeded the 1 MiB limit")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise PluginExecutionError("Plugin host returned an invalid response") from error
        if completed.returncode != 0 or not response.get("ok"):
            code = str(response.get("code") or "PLUGIN_EXECUTION_FAILED")
            raise PluginExecutionError(f"Plugin execution failed safely ({code})")
        result = response.get("result")
        if not isinstance(result, dict):
            raise PluginExecutionError("Plugin analyzer returned an invalid result")
        return cast(dict[str, object], result)


def validate_plugin_file(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.suffix != ".py":
        raise ValueError("Plugin validation requires a Python entry-point file")
    if resolved.stat().st_size > MAX_PLUGIN_OUTPUT_BYTES:
        raise ValueError("Plugin entry-point files cannot exceed 1 MiB")
    fingerprint = hashlib.sha256(resolved.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(
        f"mediasensei_validation_{fingerprint[:12]}", resolved
    )
    if spec is None or spec.loader is None:
        raise ValueError("Plugin file could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        registration = validate_plugin_object(getattr(module, "PLUGIN", None))
    except Exception as error:
        from mediasensei_plugin_sdk import PluginValidationError

        if isinstance(error, PluginValidationError):
            raise
        raise ValueError(f"Plugin import failed safely ({type(error).__name__})") from error
    return {
        "valid": True,
        "api_version": "1.5",
        "name": registration.manifest.name,
        "version": registration.manifest.version,
        "capabilities": list(registration.manifest.capabilities),
        "permissions": list(registration.manifest.permissions),
        "sha256": fingerprint,
    }


def _isolated_environment() -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "PATHEXT"}
    }
    core_source = str(Path(__file__).resolve().parents[2])
    sdk_source = str(Path(__file__).resolve().parents[4] / "plugin-sdk" / "src")
    allowed["PYTHONPATH"] = os.pathsep.join((core_source, sdk_source))
    allowed["PYTHONIOENCODING"] = "utf-8"
    allowed["MEDIASENSEI_PLUGIN_HOST"] = "1"
    return allowed


def _sdk_spec(spec: AcquisitionSpec) -> SDKAcquisitionSpec:
    return SDKAcquisitionSpec(
        modality=spec.modality.value,
        topic=spec.topic,
        target=SDKAcquisitionTarget(spec.target.unit.value, spec.target.count),
        categories=spec.categories,
        queries=spec.queries,
        provider_ids=spec.provider_ids,
        min_width=spec.min_width,
        min_height=spec.min_height,
        min_quality=spec.min_quality,
        reject_corrupt=spec.reject_corrupt,
        reject_exact_duplicates=spec.reject_exact_duplicates,
        reject_near_duplicates=spec.reject_near_duplicates,
        reject_text_heavy=spec.reject_text_heavy,
        relevance_strategy=spec.relevance_strategy,
        replenish_until_target=spec.replenish_until_target,
        near_duplicate_threshold=spec.near_duplicate_threshold,
        budget=SDKAcquisitionBudget(**asdict(spec.budget)),
    )


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    return int(str(value)) if value is not None else None


def _now() -> str:
    return datetime.now(UTC).isoformat()
