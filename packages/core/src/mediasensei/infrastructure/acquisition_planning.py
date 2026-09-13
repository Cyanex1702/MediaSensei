from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any, Protocol, cast

from mediasensei.domain.acquisition import (
    AcquisitionBudget,
    AcquisitionDecision,
    AcquisitionDecisionKind,
    AcquisitionModality,
    AcquisitionReason,
    AcquisitionSpec,
    DiscoveryPage,
    DiscoveryRequest,
    TargetSpec,
    TargetUnit,
    YieldSnapshot,
)


class DiscoveryProvider(Protocol):
    provider_id: str
    version: str

    def available(self) -> bool: ...

    def capabilities(self) -> dict[str, Any]: ...

    def search(self, request: DiscoveryRequest) -> DiscoveryPage: ...


class PromptPlannerProvider(Protocol):
    planner_id: str
    version: str

    def plan(self, prompt: str) -> AcquisitionSpec: ...


class RelevanceEvaluator(Protocol):
    evaluator_id: str
    version: str

    def evaluate(self, spec: AcquisitionSpec, candidate: dict[str, Any]) -> AcquisitionDecision: ...


class DiscoveryRegistry:
    def __init__(self, providers: Iterable[DiscoveryProvider] = ()) -> None:
        self._providers: dict[str, DiscoveryProvider] = {}
        for provider in providers:
            self.register(provider)

    @classmethod
    def defaults(cls) -> DiscoveryRegistry:
        from mediasensei.infrastructure.acquisition_discovery import (
            DirectUrlDiscoveryProvider,
            OpenverseDiscoveryProvider,
            WikimediaCommonsDiscoveryProvider,
        )
        from mediasensei.infrastructure.plugins import PluginRuntime

        registry = cls(
            (
                WikimediaCommonsDiscoveryProvider(),
                OpenverseDiscoveryProvider(),
                DirectUrlDiscoveryProvider(),
            )
        )
        for provider in PluginRuntime.discover().discovery_providers():
            try:
                registry.register(provider)
            except ValueError:
                continue
        return registry

    def register(self, provider: DiscoveryProvider) -> None:
        provider_id = provider.provider_id.strip().lower()
        if not provider_id:
            raise ValueError("Discovery providers require a stable id")
        if provider_id in self._providers:
            raise ValueError(f"Duplicate discovery provider id: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> DiscoveryProvider:
        try:
            return self._providers[provider_id.strip().lower()]
        except KeyError as error:
            raise LookupError(f"Discovery provider is not installed: {provider_id}") from error

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {
                "id": provider.provider_id,
                "version": provider.version,
                "available": provider.available(),
                **provider.capabilities(),
            }
            for provider in sorted(self._providers.values(), key=lambda item: item.provider_id)
        ]


class RuleBasedPromptPlanner:
    planner_id = "rule-based"
    version = "1.0.1"

    def plan(self, prompt: str) -> AcquisitionSpec:
        clean = " ".join(prompt.split())
        if not clean:
            raise ValueError("An acquisition prompt cannot be empty")
        target_match = re.search(
            r"\b([\d,]+)\s+(?:usable\s+|accepted\s+)?(?:images?|photos?|photographs?|pictures?)\b",
            clean,
            re.IGNORECASE,
        )
        if target_match is None:
            target_match = re.search(
                r"\b(?:find|get|collect|acquire|want|need|download)\s+(?:me\s+)?([\d,]+)\b(?!\s*(?:px|pixels))",
                clean, re.IGNORECASE,
            )
        target = int(target_match.group(1).replace(",", "")) if target_match else 100
        dimensions = re.search(r"\b(\d{2,5})\s*[x×]\s*(\d{2,5})\b", clean)
        minimum = re.search(
            r"(?:at least|minimum|min\.?)[^\d]{0,12}(\d{2,5})\s*(?:px|pixels?)",
            clean,
            re.IGNORECASE,
        )
        min_width = (
            int(dimensions.group(1)) if dimensions else int(minimum.group(1)) if minimum else 512
        )
        min_height = int(dimensions.group(2)) if dimensions else min_width
        topic_match = re.search(
            r"(?:images?|photos?|photographs?|pictures?)\s+of\s+(.+?)(?:[.;]|\b(?:include|minimum|avoid)\b|$)",
            clean,
            re.IGNORECASE,
        )
        topic = topic_match.group(1).strip(" :-") if topic_match else _fallback_topic(clean)
        categories = _prompt_categories(prompt)
        return AcquisitionSpec(
            modality=AcquisitionModality.IMAGE,
            topic=topic,
            target=TargetSpec(TargetUnit.ACCEPTED_ASSETS, target),
            categories=categories,
            queries=generate_queries(topic, categories),
            provider_ids=("wikimedia-commons", "openverse"),
            min_width=min_width,
            min_height=min_height,
            reject_text_heavy=(
                "text-heavy" in clean.casefold() or "text heavy" in clean.casefold()
            ),
            budget=AcquisitionBudget(max_candidates=max(target * 3, min(100, target + 20))),
        )


class CapabilityResolver:
    def resolve(
        self,
        *,
        project_policy: str,
        providers: DiscoveryRegistry,
        preferred_strategy: str = "auto",
        ai_planner_available: bool = False,
        semantic_model_available: bool = False,
        gpu_available: bool = False,
    ) -> dict[str, Any]:
        remote_allowed = project_policy in {"approved_external", "unrestricted"}
        planner = "ai" if ai_planner_available and preferred_strategy != "manual" else "rule-based"
        if not remote_allowed:
            planner = "manual" if preferred_strategy == "manual" else "rule-based"
        relevance = (
            "local-semantic-gpu"
            if semantic_model_available and gpu_available
            else "local-semantic-cpu"
            if semantic_model_available
            else "metadata+human-review"
        )
        return {
            "planner": planner,
            "relevance": relevance,
            "remote_acquisition_allowed": remote_allowed,
            "remote_processing_allowed": project_policy == "unrestricted",
            "providers": [item for item in providers.capabilities() if item["available"]],
            "degraded": not ai_planner_available or not semantic_model_available,
            "no_ai_supported": True,
        }


class TargetYieldController:
    def __init__(self, *, minimum_batch: int = 10, maximum_batch: int = 100) -> None:
        self.minimum_batch = max(1, minimum_batch)
        self.maximum_batch = max(self.minimum_batch, maximum_batch)

    def next_batch(self, snapshot: YieldSnapshot, remaining_budget: int) -> int:
        if snapshot.remaining == 0 or remaining_budget <= 0:
            return 0
        estimated = snapshot.estimated_additional()
        return min(
            remaining_budget,
            max(self.minimum_batch, min(self.maximum_batch, estimated)),
        )


class MetadataRelevanceEvaluator:
    evaluator_id = "metadata-keyword"
    version = "1.0.0"

    def evaluate(self, spec: AcquisitionSpec, candidate: dict[str, Any]) -> AcquisitionDecision:
        if spec.relevance_strategy == "disabled":
            return AcquisitionDecision(
                AcquisitionDecisionKind.ACCEPT,
                AcquisitionReason.ACCEPTED,
                self.evaluator_id,
                self.version,
                {"strategy": "disabled"},
            )
        if spec.relevance_strategy == "manual":
            return AcquisitionDecision(
                AcquisitionDecisionKind.REVIEW,
                AcquisitionReason.NEEDS_REVIEW,
                self.evaluator_id,
                self.version,
                {"strategy": "manual"},
            )
        expected = _keywords(" ".join((spec.topic, *spec.categories)))
        observed = _keywords(
            " ".join(str(candidate.get(field) or "") for field in ("title", "description", "query"))
        )
        overlap = sorted(expected & observed)
        score = len(overlap) / max(1, min(5, len(expected)))
        if overlap:
            return AcquisitionDecision(
                AcquisitionDecisionKind.ACCEPT,
                AcquisitionReason.ACCEPTED,
                self.evaluator_id,
                self.version,
                {"keyword_overlap": overlap, "score": round(score, 4)},
            )
        decision = (
            AcquisitionDecisionKind.REJECT
            if spec.relevance_strategy == "metadata"
            else AcquisitionDecisionKind.REVIEW
        )
        reason = (
            AcquisitionReason.IRRELEVANT
            if decision is AcquisitionDecisionKind.REJECT
            else AcquisitionReason.NEEDS_REVIEW
        )
        return AcquisitionDecision(
            decision,
            reason,
            self.evaluator_id,
            self.version,
            {"keyword_overlap": [], "score": 0.0},
        )


def spec_to_dict(spec: AcquisitionSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["modality"] = spec.modality.value
    payload["target"]["unit"] = spec.target.unit.value
    return payload


def spec_from_dict(payload: dict[str, Any]) -> AcquisitionSpec:
    target_payload = cast(dict[str, Any], payload.get("target") or {})
    budget_payload = cast(dict[str, Any], payload.get("budget") or {})
    return AcquisitionSpec(
        modality=AcquisitionModality(str(payload.get("modality") or "image")),
        topic=str(payload.get("topic") or ""),
        target=TargetSpec(
            TargetUnit(str(target_payload.get("unit") or "accepted_assets")),
            int(target_payload.get("count") or 100),
        ),
        allowed_licenses=tuple(str(v).casefold() for v in payload.get("allowed_licenses", [])),
        allowed_domains=tuple(str(v).casefold() for v in payload.get("allowed_domains", [])),
        categories=tuple(cast(list[str], payload.get("categories") or [])),
        queries=tuple(cast(list[str], payload.get("queries") or [])),
        provider_ids=tuple(
            cast(
                list[str],
                payload.get("provider_ids") or ["wikimedia-commons"],
            )
        ),
        min_width=int(payload.get("min_width") or 512),
        min_height=int(payload.get("min_height") or 512),
        min_quality=float(payload.get("min_quality") or 0.0),
        reject_corrupt=bool(payload.get("reject_corrupt", True)),
        reject_exact_duplicates=bool(payload.get("reject_exact_duplicates", True)),
        reject_near_duplicates=bool(payload.get("reject_near_duplicates", True)),
        reject_text_heavy=bool(payload.get("reject_text_heavy", False)),
        relevance_strategy=str(payload.get("relevance_strategy") or "auto"),
        replenish_until_target=bool(payload.get("replenish_until_target", True)),
        near_duplicate_threshold=int(payload.get("near_duplicate_threshold") or 8),
        budget=AcquisitionBudget(
            max_candidates=int(budget_payload.get("max_candidates") or 1500),
            max_download_bytes=int(budget_payload.get("max_download_bytes") or 25 * 1024**3),
            max_storage_bytes=int(budget_payload.get("max_storage_bytes") or 20 * 1024**3),
            max_requests=int(budget_payload.get("max_requests") or 2000),
            max_external_cost=(
                float(budget_payload["max_external_cost"])
                if budget_payload.get("max_external_cost") is not None
                else None
            ),
        ),
    )


def generate_queries(topic: str, categories: tuple[str, ...] = ()) -> tuple[str, ...]:
    base = [topic, f"{topic} photography", f"real {topic}"]
    base.extend(f"{category} {topic} photography" for category in categories)
    return tuple(dict.fromkeys(value.strip() for value in base if value.strip()))[:24]


def _fallback_topic(prompt: str) -> str:
    prompt = re.split(r"\b(?:at least|minimum|avoid|reject|include)\b", prompt, maxsplit=1, flags=re.IGNORECASE)[0]
    clean = re.sub(
        r"\b(?:get|find|acquire|download|collect|me|please|i|want|need)\b",
        " ",
        prompt,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\b[\d,]+\b|\b(?:images?|photos?|photographs?|pictures?|usable|accepted)\b",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    return " ".join(clean.split()).strip(" ,.;:")[:500] or "images"


def _prompt_categories(prompt: str) -> tuple[str, ...]:
    match = re.search(
        r"\binclude\b\s*:?(.*?)(?:\bminimum\b|\bavoid\b|\breject\b|$)",
        prompt,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ()
    values = re.split(r"[,;\n]|\band\b", match.group(1), flags=re.IGNORECASE)
    return tuple(
        dict.fromkeys(" ".join(value.split()).strip(" .:-") for value in values if value.strip())
    )[:20]


def _keywords(value: str) -> set[str]:
    stop = {
        "a",
        "an",
        "and",
        "the",
        "of",
        "for",
        "real",
        "image",
        "images",
        "photo",
        "photos",
        "photography",
    }
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) > 2 and word not in stop
    }
