from __future__ import annotations

import os
import socket
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event
from typing import Any
from uuid import uuid4

from mediasensei.domain.jobs import JobSnapshot, WorkItem
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.scheduler import AdaptiveScheduler, HardwareProfile

Processor = Callable[[WorkItem, dict[str, Any]], dict[str, Any]]


class ProcessorRegistry:
    def __init__(self) -> None:
        self._processors: dict[str, Processor] = {}
        self.register("core.identity", _identity_processor)

    def register(self, processor_id: str, processor: Processor) -> None:
        if not processor_id.strip():
            raise ValueError("Processor id cannot be empty")
        self._processors[processor_id] = processor

    def get(self, processor_id: str) -> Processor:
        try:
            return self._processors[processor_id]
        except KeyError as error:
            raise LookupError(f"Processor is not installed: {processor_id}") from error


class LocalWorker:
    """Bounded local worker with leases, checkpoints, cache reuse, and retry isolation."""

    def __init__(
        self,
        queue: JobQueue,
        *,
        registry: ProcessorRegistry | None = None,
        scheduler: AdaptiveScheduler | None = None,
        hardware: HardwareProfile | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        self.queue = queue
        self.registry = registry or ProcessorRegistry()
        if registry is None:
            try:
                from mediasensei.infrastructure.images import register_image_processors

                register_image_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Core-only installations remain usable; image jobs report a missing processor.
                pass
            try:
                from mediasensei.infrastructure.tabular import register_tabular_processors

                register_tabular_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Data extras are optional; tabular jobs report a missing processor.
                pass
            try:
                from mediasensei.infrastructure.documents import register_document_processors

                register_document_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Optional learned providers can fail independently; local indexing remains isolated.
                pass
            try:
                from mediasensei.infrastructure.media import register_media_processors

                register_media_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Media processors remain discoverable even when FFmpeg is not installed.
                pass
            try:
                from mediasensei.infrastructure.providers import register_provider_processors

                register_provider_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Provider extras and credentials are resolved only when a remote job runs.
                pass
            try:
                from mediasensei.infrastructure.acquisition import (
                    register_acquisition_processors,
                )

                register_acquisition_processors(self.registry, queue.catalog)
            except RuntimeError:
                # Acquisition stays optional when image dependencies are unavailable.
                pass
        if registry is None:
            try:
                from mediasensei.operations import register_operation_processors
                register_operation_processors(self.registry, queue.catalog)
            except ImportError:
                pass
        if registry is None:
            from mediasensei.multimodal import register_batch_processors
            register_batch_processors(self.registry, queue.catalog)
            from mediasensei.integrations import register_integration_processors
            register_integration_processors(self.registry, queue.catalog)
        self.scheduler = scheduler or AdaptiveScheduler()
        self._fixed_hardware = hardware
        self.hardware = hardware or HardwareProfile.detect(queue.catalog.workspace)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        self.lease_seconds = max(5, lease_seconds)

    def run_once(self, *, max_items: int | None = None) -> JobSnapshot | None:
        job = self.queue.claim_next(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return None

        if self._fixed_hardware is None:
            self.hardware = HardwareProfile.detect(self.queue.catalog.workspace)
        decision = self.scheduler.decide(
            self.hardware,
            job.profile,
            job.processor.resource_hints,
        )
        self.queue.log_event(
            job.id,
            "warning" if decision.warnings else "info",
            "schedule_decision",
            f"Scheduler selected concurrency {decision.max_concurrency}",
            {"warnings": list(decision.warnings), "profile": decision.profile.value},
        )
        if decision.paused_for_pressure:
            return self.queue.pause(job.id)

        try:
            processor = self.registry.get(job.processor.id)
        except LookupError as error:
            for item in self.queue.claim_items(job.id, max(1, job.total_items)):
                self.queue.fail_item(job.id, item.id, error)
            return self.queue.get(job.id)

        processed_this_run = 0
        while True:
            current = self.queue.get(job.id)
            if current.state.value != "running" or current.terminal:
                return current
            if max_items is not None and processed_this_run >= max_items:
                return self.queue.release(job.id, self.worker_id)

            capacity = decision.max_concurrency
            if max_items is not None:
                capacity = min(capacity, max_items - processed_this_run)
            items = self.queue.claim_items(job.id, capacity)
            if not items:
                return self.queue.get(job.id)

            uncached: list[tuple[WorkItem, str | None]] = []
            for item in items:
                cache_key = (
                    job.processor.cache_key(item.input_hash, job.parameters)
                    if job.processor.deterministic and job.processor.cacheable
                    else None
                )
                cached = self.queue.cached_output(cache_key) if cache_key else None
                if cached is not None:
                    self.queue.complete_item(
                        job.id,
                        item.id,
                        cached,
                        cache_key=cache_key,
                        cached=True,
                    )
                    processed_this_run += 1
                else:
                    uncached.append((item, cache_key))

            if uncached:
                with ThreadPoolExecutor(
                    max_workers=min(decision.max_concurrency, len(uncached)),
                    thread_name_prefix="mediasensei",
                ) as executor:
                    futures = {
                        executor.submit(processor, item, job.parameters): (item, cache_key)
                        for item, cache_key in uncached
                    }
                    pending = set(futures)
                    while pending:
                        done, pending = wait(pending, timeout=self.lease_seconds / 3, return_when=FIRST_COMPLETED)
                        current = self.queue.get(job.id)
                        if current.state.value != "running":
                            return current
                        self.queue.renew_lease(job.id, self.worker_id, lease_seconds=self.lease_seconds)
                        for future in done:
                            item, cache_key = futures[future]
                            try:
                                output = future.result()
                                if not isinstance(output, dict):
                                    raise TypeError("Processors must return a dictionary")
                                if cache_key is not None:
                                    self.queue.store_cache(
                                        cache_key=cache_key,
                                        processor=job.processor,
                                        input_hash=item.input_hash,
                                        parameters=job.parameters,
                                        output=output,
                                    )
                                self.queue.complete_item(
                                    job.id,
                                    item.id,
                                    output,
                                    cache_key=cache_key,
                                )
                            except Exception as error:  # noqa: BLE001 - isolate processor/plugin failures
                                self.queue.fail_item(job.id, item.id, error)
                            processed_this_run += 1
            snapshot = self.queue.get(job.id)
            if snapshot.terminal:
                return snapshot
            self.queue.renew_lease(
                job.id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )

    def run_forever(
        self,
        *,
        stop_event: Event | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        stop = stop_event or Event()
        while not stop.is_set():
            job = self.run_once()
            if job is None:
                stop.wait(max(0.05, min(poll_interval, 5.0)))


def _identity_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_hash": item.input_hash,
        "input_ref": item.input_ref,
        "parameters": parameters,
    }
