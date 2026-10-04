from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from mediasensei.domain.jobs import (
    ItemState,
    JobSnapshot,
    JobState,
    ProcessorSpec,
    ResourceHints,
    ResourceLevel,
    RuntimeProfile,
    WorkItem,
)
from mediasensei.infrastructure.catalog import Catalog

_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    input_hash TEXT NOT NULL,
    input_ref TEXT NOT NULL,
    position INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    cache_key TEXT,
    output_json TEXT,
    error_json TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, position)
);
CREATE INDEX IF NOT EXISTS idx_job_items_job_state_position
ON job_items(job_id, state, position);
CREATE TABLE IF NOT EXISTS processing_cache (
    cache_key TEXT PRIMARY KEY,
    processor_id TEXT NOT NULL,
    processor_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    model_revision TEXT,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_processing_cache_processor_input
ON processing_cache(processor_id, processor_version, input_hash);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job_id_id ON job_events(job_id, id);
"""

_JOB_COLUMNS = {
    "profile": "TEXT NOT NULL DEFAULT 'balanced'",
    "processor_id": "TEXT NOT NULL DEFAULT 'core.identity'",
    "processor_version": "TEXT NOT NULL DEFAULT '1.0.0'",
    "deterministic": "INTEGER NOT NULL DEFAULT 1",
    "cacheable": "INTEGER NOT NULL DEFAULT 1",
    "model_revision": "TEXT",
    "parameters_json": "TEXT NOT NULL DEFAULT '{}'",
    "resource_hints_json": "TEXT NOT NULL DEFAULT '{}'",
    "total_items": "INTEGER NOT NULL DEFAULT 0",
    "processed_count": "INTEGER NOT NULL DEFAULT 0",
    "failed_count": "INTEGER NOT NULL DEFAULT 0",
    "skipped_count": "INTEGER NOT NULL DEFAULT 0",
    "cached_count": "INTEGER NOT NULL DEFAULT 0",
    "lease_owner": "TEXT",
    "lease_expires_at": "TEXT",
    "started_at": "TEXT",
    "completed_at": "TEXT",
    "last_error": "TEXT",
}


class JobQueue:
    """SQLite-backed, restart-safe local job queue and processing cache."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._migrate()

    def _migrate(self) -> None:
        with self.catalog.connect() as connection:
            existing = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name, definition in _JOB_COLUMNS.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            connection.executescript(_JOB_SCHEMA)
            connection.execute("DROP INDEX IF EXISTS idx_jobs_claimable")
            connection.execute(
                """CREATE INDEX idx_jobs_claimable
                   ON jobs(state, created_at)"""
            )
            connection.execute("PRAGMA optimize")

    def enqueue(
        self,
        *,
        project_id: str,
        kind: str,
        processor: ProcessorSpec,
        items: Iterable[WorkItem],
        parameters: dict[str, Any] | None = None,
        profile: RuntimeProfile = RuntimeProfile.BALANCED,
    ) -> JobSnapshot:
        work_items = sorted(items, key=lambda item: item.position)
        if not work_items:
            raise ValueError("A job requires at least one work item")
        if len({item.position for item in work_items}) != len(work_items):
            raise ValueError("Work item positions must be unique")

        job_id = str(uuid4())
        timestamp = _now()
        params = parameters or {}
        hints = {
            "cpu": processor.resource_hints.cpu.value,
            "memory": processor.resource_hints.memory.value,
            "disk": processor.resource_hints.disk.value,
            "network": processor.resource_hints.network.value,
            "gpu": processor.resource_hints.gpu.value,
            "vram": processor.resource_hints.vram.value,
        }
        with self.catalog.connect() as connection:
            connection.execute(
                """INSERT INTO jobs (
                    id, project_id, kind, state, progress, checkpoint_json,
                    created_at, updated_at, profile, processor_id,
                    processor_version, deterministic, cacheable, model_revision,
                    parameters_json, resource_hints_json, total_items
                ) VALUES (?, ?, ?, 'queued', 0, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    project_id,
                    kind,
                    timestamp,
                    timestamp,
                    profile.value,
                    processor.id,
                    processor.version,
                    int(processor.deterministic),
                    int(processor.cacheable),
                    processor.model_revision,
                    _json(params),
                    _json(hints),
                    len(work_items),
                ),
            )
            connection.executemany(
                """INSERT INTO job_items (
                    id, job_id, input_hash, input_ref, position, state, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                [
                    (
                        str(uuid4()),
                        job_id,
                        item.input_hash,
                        item.input_ref,
                        item.position,
                        timestamp,
                    )
                    for item in work_items
                ],
            )
            self._event(
                connection,
                job_id,
                "info",
                "job_queued",
                f"Queued {len(work_items)} work items",
                {"profile": profile.value},
            )
        return self.get(job_id)

    def get(self, job_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job: {job_id}")
        return self._snapshot(row)

    def list_jobs(self, project_id: str | None = None, *, limit: int = 100) -> list[JobSnapshot]:
        with self.catalog.connect() as connection:
            if project_id is None:
                rows = connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, max(1, min(limit, 500))),
                ).fetchall()
        return [self._snapshot(row) for row in rows]

    def _snapshot(self, row: sqlite3.Row) -> JobSnapshot:
        hints_data = json.loads(row["resource_hints_json"] or "{}")
        hints = ResourceHints(
            cpu=ResourceLevel(hints_data.get("cpu", "low")),
            memory=ResourceLevel(hints_data.get("memory", "low")),
            disk=ResourceLevel(hints_data.get("disk", "low")),
            network=ResourceLevel(hints_data.get("network", "none")),
            gpu=ResourceLevel(hints_data.get("gpu", "none")),
            vram=ResourceLevel(hints_data.get("vram", "none")),
        )
        processor = ProcessorSpec(
            id=row["processor_id"],
            version=row["processor_version"],
            deterministic=bool(row["deterministic"]),
            cacheable=bool(row["cacheable"]),
            model_revision=row["model_revision"],
            resource_hints=hints,
        )
        return JobSnapshot(
            id=row["id"],
            project_id=row["project_id"],
            kind=row["kind"],
            state=JobState(row["state"]),
            profile=RuntimeProfile(row["profile"]),
            processor=processor,
            parameters=json.loads(row["parameters_json"] or "{}"),
            total_items=row["total_items"],
            processed_count=row["processed_count"],
            failed_count=row["failed_count"],
            skipped_count=row["skipped_count"],
            cached_count=row["cached_count"],
            progress=row["progress"],
            checkpoint=json.loads(row["checkpoint_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def recover_stale(self, *, now: datetime | None = None) -> int:
        timestamp = (now or datetime.now(UTC)).isoformat()
        with self.catalog.connect() as connection:
            stale = connection.execute(
                """SELECT id FROM jobs
                   WHERE state = 'running'
                     AND lease_expires_at IS NOT NULL
                     AND lease_expires_at <= ?""",
                (timestamp,),
            ).fetchall()
            for row in stale:
                connection.execute(
                    """UPDATE job_items SET state = 'pending', updated_at = ?
                       WHERE job_id = ? AND state = 'running'""",
                    (timestamp, row["id"]),
                )
                connection.execute(
                    """UPDATE jobs SET state = 'queued', lease_owner = NULL,
                       lease_expires_at = NULL, updated_at = ? WHERE id = ?""",
                    (timestamp, row["id"]),
                )
                self._event(
                    connection,
                    row["id"],
                    "warning",
                    "lease_recovered",
                    "Recovered an interrupted worker lease",
                    {},
                )
        return len(stale)

    def claim_next(self, worker_id: str, *, lease_seconds: int = 60) -> JobSnapshot | None:
        now = datetime.now(UTC)
        self.recover_stale(now=now)
        with self.catalog.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE state = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            expires = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
            connection.execute(
                """UPDATE jobs SET state = 'running', lease_owner = ?,
                   lease_expires_at = ?, started_at = COALESCE(started_at, ?),
                   updated_at = ? WHERE id = ? AND state = 'queued'""",
                (worker_id, expires, now.isoformat(), now.isoformat(), row["id"]),
            )
            self._event(
                connection,
                row["id"],
                "info",
                "job_claimed",
                f"Worker {worker_id} claimed the job",
                {"lease_seconds": lease_seconds},
            )
        return self.get(row["id"])

    def renew_lease(self, job_id: str, worker_id: str, *, lease_seconds: int = 60) -> None:
        now = datetime.now(UTC)
        expires = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'running' AND lease_owner = ?""",
                (expires, now.isoformat(), job_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Worker no longer owns the job lease")

    def claim_items(self, job_id: str, limit: int) -> list[WorkItem]:
        claimed: list[WorkItem] = []
        timestamp = _now()
        with self.catalog.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT id, input_hash, input_ref, position FROM job_items
                   WHERE job_id = ? AND state = 'pending'
                   ORDER BY position LIMIT ?""",
                (job_id, max(1, limit)),
            ).fetchall()
            for row in rows:
                cursor = connection.execute(
                    """UPDATE job_items SET state = 'running',
                       attempt_count = attempt_count + 1, updated_at = ?
                       WHERE id = ? AND state = 'pending'""",
                    (timestamp, row["id"]),
                )
                if cursor.rowcount:
                    claimed.append(
                        WorkItem(
                            id=row["id"],
                            input_hash=row["input_hash"],
                            input_ref=row["input_ref"],
                            position=row["position"],
                        )
                    )
        return claimed

    def cached_output(self, cache_key: str) -> dict[str, Any] | None:
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT output_json FROM processing_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE processing_cache SET hit_count = hit_count + 1,
                   last_accessed_at = ? WHERE cache_key = ?""",
                (_now(), cache_key),
            )
        return json.loads(row["output_json"])

    def store_cache(
        self,
        *,
        cache_key: str,
        processor: ProcessorSpec,
        input_hash: str,
        parameters: dict[str, Any],
        output: dict[str, Any],
    ) -> None:
        timestamp = _now()
        parameters_hash = ProcessorSpec(
            id="parameters",
            version="1",
        ).cache_key("", parameters)
        with self.catalog.connect() as connection:
            connection.execute(
                """INSERT INTO processing_cache (
                    cache_key, processor_id, processor_version, input_hash,
                    parameters_hash, model_revision, output_json, created_at,
                    last_accessed_at, hit_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(cache_key) DO UPDATE SET
                    output_json = excluded.output_json,
                    last_accessed_at = excluded.last_accessed_at""",
                (
                    cache_key,
                    processor.id,
                    processor.version,
                    input_hash,
                    parameters_hash,
                    processor.model_revision,
                    _json(output),
                    timestamp,
                    timestamp,
                ),
            )

    def complete_item(
        self,
        job_id: str,
        item_id: str,
        output: dict[str, Any],
        *,
        cache_key: str | None = None,
        cached: bool = False,
    ) -> JobSnapshot:
        state = ItemState.CACHED if cached else ItemState.COMPLETED
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE job_items SET state = ?, cache_key = ?,
                   output_json = ?, error_json = NULL, updated_at = ?
                   WHERE id = ? AND job_id = ?""",
                (state.value, cache_key, _json(output), _now(), item_id, job_id),
            )
        return self._refresh(job_id)

    def fail_item(self, job_id: str, item_id: str, error: Exception) -> JobSnapshot:
        details = {
            "type": type(error).__name__,
            "message": str(error)[:1000],
        }
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE job_items SET state = 'failed', error_json = ?,
                   updated_at = ? WHERE id = ? AND job_id = ?""",
                (_json(details), _now(), item_id, job_id),
            )
            self._event(
                connection,
                job_id,
                "error",
                "item_failed",
                f"Item {item_id} failed",
                details,
            )
        return self._refresh(job_id)

    def _refresh(self, job_id: str) -> JobSnapshot:
        timestamp = _now()
        with self.catalog.connect() as connection:
            counts = {
                row["state"]: row["count"]
                for row in connection.execute(
                    """SELECT state, COUNT(*) AS count FROM job_items
                       WHERE job_id = ? GROUP BY state""",
                    (job_id,),
                ).fetchall()
            }
            job = connection.execute(
                "SELECT total_items, state FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                raise KeyError(f"Unknown job: {job_id}")

            processed = counts.get("completed", 0)
            cached = counts.get("cached", 0)
            failed = counts.get("failed", 0)
            skipped = counts.get("skipped", 0)
            completed_units = processed + cached + failed + skipped
            progress = round((completed_units / max(1, job["total_items"])) * 100)
            checkpoint_row = connection.execute(
                """SELECT MAX(position) AS position FROM job_items
                   WHERE job_id = ? AND state IN ('completed', 'cached', 'failed', 'skipped')""",
                (job_id,),
            ).fetchone()
            checkpoint = {
                "last_position": checkpoint_row["position"],
                "completed_units": completed_units,
                "updated_at": timestamp,
            }

            state = job["state"]
            completed_at: str | None = None
            if completed_units >= job["total_items"] and state not in {
                "paused",
                "cancelled",
            }:
                state = JobState.COMPLETED_WITH_ERRORS.value if failed else JobState.COMPLETED.value
                completed_at = timestamp

            connection.execute(
                """UPDATE jobs SET state = ?, processed_count = ?,
                   failed_count = ?, skipped_count = ?, cached_count = ?,
                   progress = ?, checkpoint_json = ?, updated_at = ?,
                   completed_at = COALESCE(?, completed_at),
                   lease_owner = CASE WHEN ? IN ('completed', 'completed_with_errors') THEN NULL ELSE lease_owner END,
                   lease_expires_at = CASE WHEN ? IN ('completed', 'completed_with_errors') THEN NULL ELSE lease_expires_at END
                   WHERE id = ?""",
                (
                    state,
                    processed,
                    failed,
                    skipped,
                    cached,
                    progress,
                    _json(checkpoint),
                    timestamp,
                    completed_at,
                    state,
                    state,
                    job_id,
                ),
            )
            if completed_at is not None:
                self._event(
                    connection,
                    job_id,
                    "info",
                    "job_finished",
                    f"Job finished with state {state}",
                    {
                        "processed": processed,
                        "cached": cached,
                        "failed": failed,
                        "skipped": skipped,
                    },
                )
        return self.get(job_id)

    def release(self, job_id: str, worker_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE job_items SET state = 'pending', updated_at = ?
                   WHERE job_id = ? AND state = 'running'""",
                (_now(), job_id),
            )
            connection.execute(
                """UPDATE jobs SET state = 'queued', lease_owner = NULL,
                   lease_expires_at = NULL, updated_at = ?
                   WHERE id = ? AND state = 'running' AND lease_owner = ?""",
                (_now(), job_id, worker_id),
            )
        return self._refresh(job_id)

    def pause(self, job_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE job_items SET state = 'pending', updated_at = ?
                   WHERE job_id = ? AND state = 'running'""",
                (_now(), job_id),
            )
            cursor = connection.execute(
                """UPDATE jobs SET state = 'paused', lease_owner = NULL,
                   lease_expires_at = NULL, updated_at = ?
                   WHERE id = ? AND state IN ('queued', 'running')""",
                (_now(), job_id),
            )
            if cursor.rowcount:
                self._event(
                    connection, job_id, "info", "job_paused", "Job paused at checkpoint", {}
                )
        return self._refresh(job_id)

    def resume(self, job_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET state = 'queued', updated_at = ?
                   WHERE id = ? AND state = 'paused'""",
                (_now(), job_id),
            )
            if cursor.rowcount:
                self._event(
                    connection, job_id, "info", "job_resumed", "Job returned to the queue", {}
                )
        return self._refresh(job_id)

    def cancel(self, job_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE job_items SET state = 'cancelled', updated_at = ?
                   WHERE job_id = ? AND state IN ('pending', 'running')""",
                (_now(), job_id),
            )
            connection.execute(
                """UPDATE jobs SET state = 'cancelled', lease_owner = NULL,
                   lease_expires_at = NULL, updated_at = ?, completed_at = ?
                   WHERE id = ? AND state NOT IN ('completed', 'completed_with_errors', 'failed', 'cancelled')""",
                (_now(), _now(), job_id),
            )
            self._event(connection, job_id, "info", "job_cancelled", "Job cancelled", {})
        return self.get(job_id)

    def retry_failed(self, job_id: str) -> JobSnapshot:
        with self.catalog.connect() as connection:
            count = connection.execute(
                """UPDATE job_items SET state = 'pending', error_json = NULL,
                   updated_at = ? WHERE job_id = ? AND state = 'failed'""",
                (_now(), job_id),
            ).rowcount
            if count:
                connection.execute(
                    """UPDATE jobs SET state = 'queued', completed_at = NULL,
                       lease_owner = NULL, lease_expires_at = NULL,
                       updated_at = ? WHERE id = ?""",
                    (_now(), job_id),
                )
                self._event(
                    connection,
                    job_id,
                    "info",
                    "failed_items_requeued",
                    f"Requeued {count} failed items",
                    {"count": count},
                )
        return self._refresh(job_id)

    def events(self, job_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT id, level, event_type, message, details_json, created_at
                   FROM job_events WHERE job_id = ? ORDER BY id DESC LIMIT ?""",
                (job_id, max(1, min(limit, 500))),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "level": row["level"],
                "event_type": row["event_type"],
                "message": row["message"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def cache_stats(self) -> dict[str, int]:
        with self.catalog.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS entries, COALESCE(SUM(hit_count), 0) AS hits
                   FROM processing_cache"""
            ).fetchone()
        return {"entries": row["entries"], "hits": row["hits"]}

    def log_event(
        self,
        job_id: str,
        level: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.catalog.connect() as connection:
            self._event(
                connection,
                job_id,
                level,
                event_type,
                message,
                details or {},
            )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        job_id: str,
        level: str,
        event_type: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO job_events (
                job_id, level, event_type, message, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, level, event_type, message, _json(details), _now()),
        )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return datetime.now(UTC).isoformat()
