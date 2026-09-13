from __future__ import annotations

import hashlib
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, cast

from mediasensei.domain.acquisition import (
    AcquisitionDecision,
    AcquisitionDecisionKind,
    AcquisitionModality,
    AcquisitionReason,
    AcquisitionRunState,
    AcquisitionSpec,
    CandidateState,
    DiscoveryRequest,
    YieldSnapshot,
)
from mediasensei.domain.jobs import ProcessorSpec, ResourceHints, ResourceLevel, WorkItem
from mediasensei.infrastructure.acquisition_discovery import (
    AcquisitionDownloader,
    AcquisitionError,
    SafeHttpDownloader,
)
from mediasensei.infrastructure.acquisition_planning import (
    CapabilityResolver,
    DiscoveryRegistry,
    MetadataRelevanceEvaluator,
    PromptPlannerProvider,
    RelevanceEvaluator,
    RuleBasedPromptPlanner,
    TargetYieldController,
    spec_from_dict,
    spec_to_dict,
)
from mediasensei.infrastructure.acquisition_repository import AcquisitionRepository
from mediasensei.infrastructure.images import ImagePipeline
from mediasensei.infrastructure.storage import ContentAddressedStore


class AcquisitionPaused(AcquisitionError):
    pass


class AcquisitionCancelled(AcquisitionError):
    pass


class AcquisitionService:
    def __init__(
        self,
        catalog: Any,
        *,
        discovery: DiscoveryRegistry | None = None,
        downloader: AcquisitionDownloader | None = None,
        planner: PromptPlannerProvider | None = None,
        relevance: RelevanceEvaluator | None = None,
        yield_controller: TargetYieldController | None = None,
        max_file_bytes: int = 512 * 1024**2,
    ) -> None:
        self.catalog = catalog
        self.repository = AcquisitionRepository(catalog)
        self.discovery = discovery or DiscoveryRegistry.defaults()
        self.downloader = downloader or SafeHttpDownloader()
        self.planner = planner or RuleBasedPromptPlanner()
        self.relevance = relevance or MetadataRelevanceEvaluator()
        self.yield_controller = yield_controller or TargetYieldController()
        self.store = ContentAddressedStore(catalog.workspace)
        self.images = ImagePipeline(self.store)
        self.max_file_bytes = max(1, max_file_bytes)

    def capabilities(self, project_id: str | None = None) -> dict[str, Any]:
        policy = self.repository.project_policy(project_id) if project_id else "local_only"
        return CapabilityResolver().resolve(
            project_policy=policy,
            providers=self.discovery,
        )

    def from_prompt(self, project_id: str, prompt: str) -> tuple[str, str]:
        spec = self.planner.plan(prompt)
        return self.repository.create_request_plan(
            project_id=project_id,
            original_prompt=prompt,
            spec=spec,
            planner_id=self.planner.planner_id,
            strategy=self.capabilities(project_id),
        )

    def create_plan(self, project_id: str, spec: AcquisitionSpec) -> tuple[str, str]:
        return self.repository.create_request_plan(
            project_id=project_id,
            original_prompt=None,
            spec=spec,
            planner_id="manual",
            strategy=self.capabilities(project_id),
        )

    def execute(self, run_id: str) -> dict[str, Any]:
        run = self.repository.run(run_id)
        policy = self.repository.project_policy(str(run["project_id"]))
        if policy == "local_only":
            self.repository.set_run_state(
                run_id,
                AcquisitionRunState.FAILED,
                reason="Remote acquisition is disabled by the project policy",
            )
            raise AcquisitionError("Remote acquisition is disabled by the project policy")
        self._check_control(run)
        self.repository.recover_incomplete(run_id)
        spec = spec_from_dict(cast(dict[str, Any], run["spec"]))
        if spec.modality is not AcquisitionModality.IMAGE:
            raise AcquisitionError("Only image acquisition is executable in this milestone")
        self.repository.set_run_state(run_id, AcquisitionRunState.DISCOVERING)
        while True:
            run = self.repository.run(run_id)
            self._check_control(run)
            snapshot = _yield_snapshot(run)
            if snapshot.accepted >= snapshot.target:
                self.repository.set_run_state(
                    run_id,
                    AcquisitionRunState.COMPLETED,
                )
                return self.repository.run(run_id)
            spec = spec_from_dict(cast(dict[str, Any], run["spec"]))
            if not spec.replenish_until_target and int(run["cycle_count"]) >= 1:
                return self._shortfall(run_id, "Planned acquisition batch completed below target")
            if snapshot.discovered >= int(run["max_candidates"]):
                return self._shortfall(
                    run_id,
                    "Maximum candidate budget reached",
                )
            if int(run["bytes_downloaded"]) >= int(run["max_download_bytes"]):
                return self._shortfall(
                    run_id,
                    "Maximum download byte budget reached",
                )

            remaining_budget = int(run["max_candidates"]) - snapshot.discovered
            batch_size = self.yield_controller.next_batch(
                snapshot,
                remaining_budget,
            )
            pending = self.repository.pending_candidates(run_id, batch_size)
            if not pending:
                added = self._discover(run_id, batch_size)
                if added == 0:
                    return self._shortfall(
                        run_id,
                        "Discovery providers returned no more candidates",
                    )
                pending = self.repository.pending_candidates(run_id, batch_size)
            self.repository.set_run_state(
                run_id,
                AcquisitionRunState.ACQUIRING,
            )
            for candidate in pending:
                self._check_control(self.repository.run(run_id))
                current = self.repository.run(run_id)
                if int(current["accepted_count"]) >= int(current["target_count"]):
                    break
                if int(current["bytes_downloaded"]) >= int(current["max_download_bytes"]):
                    break
                self._process_candidate(spec, current, candidate)
            updated = self.repository.run(run_id)
            next_batch = self.yield_controller.next_batch(
                _yield_snapshot(updated),
                int(updated["max_candidates"]) - int(updated["discovered_count"]),
            )
            self.repository.update_cycle(run_id, next_batch)
            self.repository.set_run_state(
                run_id,
                AcquisitionRunState.REPLENISHING,
            )

    def _discover(self, run_id: str, batch_size: int) -> int:
        self.repository.set_run_state(
            run_id,
            AcquisitionRunState.DISCOVERING,
        )
        run = self.repository.run(run_id)
        request_budget = spec_from_dict(cast(dict[str, Any], run["spec"])).budget.max_requests
        added = 0
        for query in self.repository.runnable_queries(run_id):
            if added >= batch_size or int(run["request_count"]) >= request_budget:
                break
            try:
                provider = self.discovery.get(str(query["provider_id"]))
                if not provider.available():
                    raise AcquisitionError(
                        f"Discovery provider unavailable: {provider.provider_id}"
                    )
                page = provider.search(
                    DiscoveryRequest(
                        query=str(query["query"]),
                        limit=max(1, batch_size - added),
                        cursor=(str(query["cursor"]) if query["cursor"] else None),
                    )
                )
                added += self.repository.record_discovery(
                    str(query["id"]),
                    page,
                )
            except Exception as error:  # noqa: BLE001 - provider isolation
                self.repository.record_discovery_error(
                    str(query["id"]),
                    error,
                )
            run = self.repository.run(run_id)
        return added

    def _process_candidate(
        self,
        spec: AcquisitionSpec,
        run: dict[str, Any],
        candidate: dict[str, Any],
    ) -> None:
        candidate_id = str(candidate["id"])
        license_name = str(candidate.get("license") or "").strip().casefold()
        if spec.allowed_licenses and license_name not in spec.allowed_licenses:
            self._decide(candidate_id, _rejection(AcquisitionReason.LICENSE_NOT_ALLOWED, "license-filter"))
            return
        domain = (urllib.parse.urlsplit(str(candidate["source_url"])).hostname or "").casefold()
        if spec.allowed_domains and not any(domain == d or domain.endswith("." + d) for d in spec.allowed_domains):
            self._decide(candidate_id, _rejection(AcquisitionReason.POLICY_BLOCKED, "source-domain-filter"))
            return
        if (
            candidate.get("declared_width") and int(candidate["declared_width"]) < spec.min_width
        ) or (
            candidate.get("declared_height") and int(candidate["declared_height"]) < spec.min_height
        ):
            self._decide(
                candidate_id,
                _rejection(AcquisitionReason.LOW_RESOLUTION, "preflight"),
            )
            return
        remaining_bytes = int(run["max_download_bytes"]) - int(run["bytes_downloaded"])
        if remaining_bytes <= 0:
            self._decide(
                candidate_id,
                _rejection(
                    AcquisitionReason.SOURCE_LIMIT_REACHED,
                    "budget",
                ),
            )
            return
        self.repository.transition_candidate(
            candidate_id,
            CandidateState.DOWNLOADING,
            increment_attempt=True,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="acquisition-",
                suffix=".download",
                dir=self.store.temp_root,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            receipt = self.downloader.download(
                str(candidate["source_url"]),
                temporary,
                max_bytes=min(self.max_file_bytes, remaining_bytes),
            )
            self.repository.record_download(candidate_id, receipt.byte_size)
            self.repository.transition_candidate(
                candidate_id,
                CandidateState.VALIDATING,
            )
            analysis = self.images.inspect(temporary)
            if not analysis.valid:
                self._decide(
                    candidate_id,
                    _rejection(AcquisitionReason.CORRUPT, "image-inspect"),
                )
                return
            if not (analysis.mime_type or "").startswith("image/"):
                self._decide(
                    candidate_id,
                    _rejection(
                        AcquisitionReason.UNSUPPORTED_FORMAT,
                        "image-inspect",
                    ),
                )
                return
            if (analysis.width or 0) < spec.min_width or (analysis.height or 0) < spec.min_height:
                self._decide(
                    candidate_id,
                    _rejection(
                        AcquisitionReason.LOW_RESOLUTION,
                        "image-inspect",
                    ),
                )
                return
            if spec.reject_exact_duplicates and self.repository.existing_asset(
                str(run["project_id"]),
                analysis.sha256,
            ):
                self._decide(
                    candidate_id,
                    _rejection(AcquisitionReason.DUPLICATE_EXACT, "sha256"),
                )
                return
            if (analysis.quality_score or 0.0) < spec.min_quality:
                self._decide(
                    candidate_id,
                    _rejection(
                        AcquisitionReason.LOW_QUALITY,
                        "image-quality",
                    ),
                )
                return
            if spec.reject_near_duplicates and analysis.perceptual_hash:
                duplicate = self.repository.near_duplicate(
                    str(run["project_id"]),
                    analysis.perceptual_hash,
                    spec.near_duplicate_threshold,
                )
                if duplicate:
                    self._decide(
                        candidate_id,
                        AcquisitionDecision(
                            AcquisitionDecisionKind.REJECT,
                            AcquisitionReason.DUPLICATE_NEAR,
                            "perceptual-hash",
                            "1.0.0",
                            {
                                "matching_asset_id": duplicate["id"],
                                "distance": duplicate["distance"],
                            },
                        ),
                    )
                    return
            relevance = self.relevance.evaluate(spec, candidate)
            latest = self.repository.run(str(run["id"]))
            if int(latest["bytes_stored"]) + receipt.byte_size > spec.budget.max_storage_bytes:
                self._decide(
                    candidate_id,
                    _rejection(AcquisitionReason.SOURCE_LIMIT_REACHED, "storage-budget"),
                )
                return
            stored = self.store.import_file(temporary)
            source_id = self.repository.create_candidate_source(candidate)
            asset_id = self.catalog.record_asset(
                project_id=str(run["project_id"]),
                source_id=source_id,
                sha256=stored.sha256,
                original_filename=_safe_filename(candidate, analysis.format),
                media_type="image",
                object_key=stored.object_key,
                byte_size=stored.byte_size,
                metadata={
                    "acquisition_run_id": run["id"],
                    "candidate_id": candidate_id,
                    "provider_id": candidate["provider_id"],
                    "remote_id": candidate["remote_id"],
                    "source_url": candidate["source_url"],
                    "landing_page_url": candidate.get("landing_page_url"),
                    "author": candidate.get("author"),
                    "license": candidate.get("license"),
                    "retrieved_url": receipt.final_url,
                    "relevance": relevance.scores,
                },
            )
            self.catalog.upsert_image_analysis(analysis)
            if relevance.decision is AcquisitionDecisionKind.REVIEW:
                self.repository.set_asset_state(asset_id, "quarantined")
            self.repository.record_candidate_decision(
                candidate_id,
                relevance,
                sha256=stored.sha256,
                asset_id=asset_id,
            )
        except Exception as error:  # noqa: BLE001 - candidate isolation
            self.repository.transition_candidate(
                candidate_id,
                CandidateState.FAILED,
                error=str(error),
            )
            if int(candidate.get("download_attempts") or 0) + 1 >= 3:
                self.repository.record_candidate_failure(candidate_id, error)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _decide(
        self,
        candidate_id: str,
        decision: AcquisitionDecision,
    ) -> None:
        self.repository.record_candidate_decision(candidate_id, decision)

    def _shortfall(self, run_id: str, reason: str) -> dict[str, Any]:
        self.repository.set_run_state(
            run_id,
            AcquisitionRunState.COMPLETED_WITH_SHORTFALL,
            reason=reason,
        )
        return self.repository.run(run_id)

    def _check_control(self, run: dict[str, Any]) -> None:
        if self.repository.project_policy(str(run["project_id"])) == "local_only":
            self.repository.set_run_state(str(run["id"]), AcquisitionRunState.CANCELLED, reason="External access disabled")
            raise AcquisitionCancelled("External access disabled for this project")
        if run["state"] == AcquisitionRunState.PAUSED.value:
            raise AcquisitionPaused("Acquisition paused at a persisted candidate checkpoint")
        if run["state"] == AcquisitionRunState.CANCELLED.value:
            raise AcquisitionCancelled("Acquisition was cancelled")

    def human_decision(
        self,
        candidate_id: str,
        decision: AcquisitionDecisionKind,
    ) -> dict[str, Any]:
        candidate = self.repository.candidate(candidate_id)
        asset_id = str(candidate["asset_id"]) if candidate.get("asset_id") else None
        if decision is AcquisitionDecisionKind.ACCEPT and asset_id is None:
            raise AcquisitionError("Only retained review candidates can be accepted manually")
        reason = (
            AcquisitionReason.USER_ACCEPTED
            if decision is AcquisitionDecisionKind.ACCEPT
            else AcquisitionReason.USER_REJECTED
            if decision is AcquisitionDecisionKind.REJECT
            else AcquisitionReason.NEEDS_REVIEW
        )
        if asset_id:
            state = "active" if decision is AcquisitionDecisionKind.ACCEPT else "excluded"
            if decision is AcquisitionDecisionKind.REVIEW:
                state = "quarantined"
            self.repository.set_asset_state(asset_id, state)
        self.repository.record_candidate_decision(
            candidate_id,
            AcquisitionDecision(
                decision,
                reason,
                "human",
                "1.0.0",
            ),
            asset_id=asset_id,
            human=True,
        )
        return self.repository.candidate(candidate_id)


def register_acquisition_processors(
    registry: Any,
    catalog: Any,
    *,
    discovery: DiscoveryRegistry | None = None,
    downloader: AcquisitionDownloader | None = None,
) -> None:
    service = AcquisitionService(
        catalog,
        discovery=discovery,
        downloader=downloader,
    )

    def processor(
        item: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(parameters.get("run_id") or item.input_ref)
        result = service.execute(run_id)
        return {
            "run_id": run_id,
            "state": result["state"],
            "accepted_count": result["accepted_count"],
            "target_count": result["target_count"],
            "discovered_count": result["discovered_count"],
            "rejected_count": result["rejected_count"],
        }

    registry.register("acquisition.image", processor)


def acquisition_processor_spec() -> ProcessorSpec:
    return ProcessorSpec(
        id="acquisition.image",
        version="1.0.0",
        deterministic=False,
        cacheable=False,
        resource_hints=ResourceHints(
            cpu=ResourceLevel.MEDIUM,
            memory=ResourceLevel.MEDIUM,
            disk=ResourceLevel.HIGH,
            network=ResourceLevel.HIGH,
        ),
    )


def acquisition_request_hash(run_id: str, spec: AcquisitionSpec) -> str:
    payload = str(spec_to_dict(spec))
    return hashlib.sha256(f"{run_id}:{payload}".encode()).hexdigest()


def _yield_snapshot(run: dict[str, Any]) -> YieldSnapshot:
    return YieldSnapshot(
        target=int(run["target_count"]),
        discovered=int(run["discovered_count"]),
        downloaded=int(run["downloaded_count"]),
        evaluated=int(run["evaluated_count"]),
        accepted=int(run["accepted_count"]),
        rejected=int(run["rejected_count"]),
        review=int(run["review_count"]),
        failed=int(run["failed_count"]),
    )


def _rejection(
    reason: AcquisitionReason,
    evaluator: str,
) -> AcquisitionDecision:
    return AcquisitionDecision(
        AcquisitionDecisionKind.REJECT,
        reason,
        evaluator,
        "1.0.0",
    )


def _safe_filename(
    candidate: dict[str, Any],
    format_name: str | None,
) -> str:
    suffix = Path(urllib.parse.urlsplit(str(candidate["source_url"])).path).suffix.casefold()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = f".{(format_name or 'image').casefold()}"
    stem = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        str(candidate.get("title") or "acquired-image"),
    )
    return f"{stem.strip('.-_')[:120] or 'acquired-image'}{suffix}"
