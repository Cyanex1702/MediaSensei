from __future__ import annotations

import json
import math
import os
import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from mediasensei.domain.acquisition import (
    AcquisitionDecision,
    AcquisitionDecisionKind,
    AcquisitionRunState,
    AcquisitionSpec,
    CandidateState,
    DiscoveryPage,
)
from mediasensei.infrastructure.acquisition_discovery import canonicalize_url
from mediasensei.infrastructure.acquisition_planning import (
    generate_queries,
    spec_from_dict,
    spec_to_dict,
)
from mediasensei.infrastructure.images import phash_distance

ACQUISITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS acquisition_requests (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 original_prompt TEXT, spec_json TEXT NOT NULL, planner_id TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acquisition_requests_project_created
 ON acquisition_requests(project_id, created_at, id);
CREATE TABLE IF NOT EXISTS acquisition_plans (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES acquisition_requests(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 spec_json TEXT NOT NULL, queries_json TEXT NOT NULL, providers_json TEXT NOT NULL,
 strategy_json TEXT NOT NULL, estimated_min_candidates INTEGER NOT NULL,
 estimated_max_candidates INTEGER NOT NULL, state TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acquisition_plans_project_created
 ON acquisition_plans(project_id, created_at, id);
CREATE TABLE IF NOT EXISTS acquisition_runs (
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES acquisition_plans(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, job_id TEXT,
 state TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0, target_count INTEGER NOT NULL,
 max_candidates INTEGER NOT NULL, max_download_bytes INTEGER NOT NULL,
 downloaded_count INTEGER NOT NULL DEFAULT 0, bytes_downloaded INTEGER NOT NULL DEFAULT 0,
 request_count INTEGER NOT NULL DEFAULT 0, cycle_count INTEGER NOT NULL DEFAULT 0,
 observed_yield REAL NOT NULL DEFAULT 0, next_batch_size INTEGER NOT NULL DEFAULT 0,
 stop_reason TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_acquisition_runs_project_created
 ON acquisition_runs(project_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_acquisition_runs_state_updated
 ON acquisition_runs(state, updated_at);
CREATE TABLE IF NOT EXISTS acquisition_queries (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES acquisition_runs(id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, query TEXT NOT NULL, origin TEXT NOT NULL,
 priority REAL NOT NULL DEFAULT 1, cursor TEXT, result_count INTEGER NOT NULL DEFAULT 0,
 evaluated_count INTEGER NOT NULL DEFAULT 0, accepted_count INTEGER NOT NULL DEFAULT 0,
 error_count INTEGER NOT NULL DEFAULT 0, exhausted INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(run_id, provider_id, query)
);
CREATE INDEX IF NOT EXISTS idx_acquisition_queries_run_priority
 ON acquisition_queries(run_id, exhausted, priority DESC, created_at);
CREATE TABLE IF NOT EXISTS acquisition_candidates (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES acquisition_runs(id) ON DELETE CASCADE,
 query_id TEXT REFERENCES acquisition_queries(id) ON DELETE SET NULL,
 provider_id TEXT NOT NULL, remote_id TEXT NOT NULL, source_url TEXT NOT NULL,
 canonical_url TEXT NOT NULL, landing_page_url TEXT, preview_url TEXT, title TEXT,
 description TEXT, mime_type TEXT, declared_width INTEGER, declared_height INTEGER,
 author TEXT, license TEXT, estimated_size INTEGER, state TEXT NOT NULL,
 download_attempts INTEGER NOT NULL DEFAULT 0, downloaded_bytes INTEGER NOT NULL DEFAULT 0,
 content_sha256 TEXT, asset_id TEXT REFERENCES assets(id), metadata_json TEXT NOT NULL DEFAULT '{}',
 error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(run_id, provider_id, remote_id), UNIQUE(run_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS idx_acquisition_candidates_run_state_created
 ON acquisition_candidates(run_id, state, created_at, id);
CREATE TABLE IF NOT EXISTS acquisition_decisions (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES acquisition_runs(id) ON DELETE CASCADE,
 candidate_id TEXT NOT NULL REFERENCES acquisition_candidates(id) ON DELETE CASCADE,
 decision TEXT NOT NULL, reason TEXT NOT NULL, evaluator_id TEXT NOT NULL,
 evaluator_version TEXT NOT NULL, scores_json TEXT NOT NULL DEFAULT '{}',
 human INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acquisition_decisions_run_reason
 ON acquisition_decisions(run_id, reason, created_at);
"""


class AcquisitionRepository:
    def __init__(self, catalog: Any) -> None:
        self.catalog = catalog
        with catalog.connect() as connection:
            connection.executescript(ACQUISITION_SCHEMA)
            connection.execute("PRAGMA optimize")

    def create_request_plan(
        self,
        *,
        project_id: str,
        original_prompt: str | None,
        spec: AcquisitionSpec,
        planner_id: str,
        strategy: dict[str, Any],
    ) -> tuple[str, str]:
        timestamp = _now()
        request_id, plan_id = str(uuid4()), str(uuid4())
        queries = spec.queries or generate_queries(spec.topic, spec.categories)
        estimated_min = max(spec.target.count, math.ceil(spec.target.count / 0.75))
        estimated_max = max(
            estimated_min,
            min(spec.budget.max_candidates, math.ceil(spec.target.count / 0.45)),
        )
        with self.catalog.connect() as connection:
            if (
                connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise KeyError(f"Project not found: {project_id}")
            connection.execute(
                """INSERT INTO acquisition_requests
                (id, project_id, original_prompt, spec_json, planner_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)""",
                (
                    request_id,
                    project_id,
                    original_prompt,
                    _json(spec_to_dict(spec)),
                    planner_id,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """INSERT INTO acquisition_plans
                (id, request_id, project_id, spec_json, queries_json, providers_json,
                 strategy_json, estimated_min_candidates, estimated_max_candidates,
                 state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)""",
                (
                    plan_id,
                    request_id,
                    project_id,
                    _json(spec_to_dict(spec)),
                    _json(list(queries)),
                    _json(list(spec.provider_ids)),
                    _json(strategy),
                    estimated_min,
                    estimated_max,
                    timestamp,
                    timestamp,
                ),
            )
        return request_id, plan_id

    def plan(self, plan_id: str) -> dict[str, Any]:
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT * FROM acquisition_plans WHERE id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Acquisition plan not found: {plan_id}")
        result = dict(row)
        for source, target in (
            ("spec_json", "spec"),
            ("queries_json", "queries"),
            ("providers_json", "providers"),
            ("strategy_json", "strategy"),
        ):
            result[target] = json.loads(str(result.pop(source)))
        return result

    def create_run(self, plan_id: str, *, dry_run_count: int | None = None) -> str:
        plan = self.plan(plan_id)
        spec = spec_from_dict(cast(dict[str, Any], plan["spec"]))
        target = min(spec.target.count, dry_run_count) if dry_run_count else spec.target.count
        max_candidates = (
            min(spec.budget.max_candidates, max(target * 3, target + 5))
            if dry_run_count
            else spec.budget.max_candidates
        )
        run_id, timestamp = str(uuid4()), _now()
        with self.catalog.connect() as connection:
            connection.execute(
                """INSERT INTO acquisition_runs
                (id, plan_id, project_id, state, dry_run, target_count, max_candidates,
                 max_download_bytes, next_batch_size, created_at, updated_at)
                VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    plan_id,
                    plan["project_id"],
                    int(bool(dry_run_count)),
                    target,
                    max_candidates,
                    spec.budget.max_download_bytes,
                    min(20 if dry_run_count else 100, max_candidates),
                    timestamp,
                    timestamp,
                ),
            )
            for provider_id in cast(list[str], plan["providers"]):
                for position, query in enumerate(cast(list[str], plan["queries"])):
                    connection.execute(
                        """INSERT INTO acquisition_queries
                        (id, run_id, provider_id, query, origin, priority, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 'plan', ?, ?, ?)""",
                        (
                            str(uuid4()),
                            run_id,
                            provider_id,
                            query,
                            max(0.1, 1.0 - position * 0.01),
                            timestamp,
                            timestamp,
                        ),
                    )
        return run_id

    def attach_job(self, run_id: str, job_id: str) -> None:
        with self.catalog.connect() as connection:
            connection.execute(
                "UPDATE acquisition_runs SET job_id = ?, updated_at = ? WHERE id = ?",
                (job_id, _now(), run_id),
            )

    def run(self, run_id: str) -> dict[str, Any]:
        with self.catalog.connect() as connection:
            row = connection.execute(
                """SELECT r.*, p.spec_json, p.queries_json, p.providers_json,
                   p.strategy_json, p.request_id FROM acquisition_runs r
                   JOIN acquisition_plans p ON p.id = r.plan_id WHERE r.id = ?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Acquisition run not found: {run_id}")
        result = dict(row)
        result["dry_run"] = bool(result["dry_run"])
        for source, target in (
            ("spec_json", "spec"),
            ("queries_json", "queries"),
            ("providers_json", "providers"),
            ("strategy_json", "strategy"),
        ):
            result[target] = json.loads(str(result.pop(source)))
        result.update(self.counts(run_id))
        return result

    def set_run_state(
        self, run_id: str, state: AcquisitionRunState, *, reason: str | None = None
    ) -> None:
        completed = (
            _now()
            if state
            in {
                AcquisitionRunState.COMPLETED,
                AcquisitionRunState.COMPLETED_WITH_SHORTFALL,
                AcquisitionRunState.FAILED,
                AcquisitionRunState.CANCELLED,
            }
            else None
        )
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                """UPDATE acquisition_runs SET state = ?, stop_reason = COALESCE(?, stop_reason),
                   completed_at = COALESCE(?, completed_at), updated_at = ? WHERE id = ?""",
                (state.value, reason, completed, _now(), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Acquisition run not found: {run_id}")

    def runnable_queries(self, run_id: str) -> list[dict[str, Any]]:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM acquisition_queries WHERE run_id = ? AND exhausted = 0
                   ORDER BY priority DESC, accepted_count DESC, created_at, id""",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_discovery(self, query_id: str, page: DiscoveryPage) -> int:
        timestamp, added = _now(), 0
        with self.catalog.connect() as connection:
            query = connection.execute(
                "SELECT run_id FROM acquisition_queries WHERE id = ?", (query_id,)
            ).fetchone()
            if query is None:
                raise KeyError(f"Acquisition query not found: {query_id}")
            run_id = str(query["run_id"])
            for candidate in page.candidates:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO acquisition_candidates
                    (id, run_id, query_id, provider_id, remote_id, source_url, canonical_url,
                     landing_page_url, preview_url, title, description, mime_type,
                     declared_width, declared_height, author, license, estimated_size,
                     state, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            'discovered', ?, ?, ?)""",
                    (
                        str(uuid4()),
                        run_id,
                        query_id,
                        candidate.provider_id,
                        candidate.remote_id,
                        candidate.source_url,
                        canonicalize_url(candidate.source_url),
                        candidate.landing_page_url,
                        candidate.preview_url,
                        candidate.title,
                        candidate.description,
                        candidate.mime_type,
                        candidate.width,
                        candidate.height,
                        candidate.author,
                        candidate.license,
                        candidate.estimated_size,
                        _json(candidate.metadata),
                        timestamp,
                        timestamp,
                    ),
                )
                added += cursor.rowcount
            connection.execute(
                """UPDATE acquisition_queries SET cursor = ?, result_count = result_count + ?,
                   exhausted = ?, updated_at = ? WHERE id = ?""",
                (page.next_cursor, added, int(page.next_cursor is None), timestamp, query_id),
            )
            connection.execute(
                """UPDATE acquisition_runs SET request_count = request_count + 1,
                   updated_at = ? WHERE id = ?""",
                (timestamp, run_id),
            )
        return added

    def record_discovery_error(self, query_id: str, error: Exception) -> None:
        del error
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE acquisition_queries SET error_count = error_count + 1,
                   exhausted = CASE WHEN error_count >= 2 THEN 1 ELSE exhausted END,
                   updated_at = ? WHERE id = ?""",
                (_now(), query_id),
            )

    def pending_candidates(self, run_id: str, limit: int) -> list[dict[str, Any]]:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT c.*, q.query FROM acquisition_candidates c
                   LEFT JOIN acquisition_queries q ON q.id = c.query_id
                   WHERE c.run_id = ? AND (c.state = 'discovered' OR
                     (c.state = 'failed' AND c.download_attempts < 3))
                   ORDER BY c.created_at, c.id LIMIT ?""",
                (run_id, max(1, limit)),
            ).fetchall()
        return [_candidate_row(row) for row in rows]

    def transition_candidate(
        self,
        candidate_id: str,
        state: CandidateState,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                """UPDATE acquisition_candidates SET state = ?, error = ?,
                   download_attempts = download_attempts + ?, updated_at = ? WHERE id = ?""",
                (state.value, _safe_error(error), int(increment_attempt), _now(), candidate_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Acquisition candidate not found: {candidate_id}")

    def recover_incomplete(self, run_id: str) -> int:
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                """UPDATE acquisition_candidates
                   SET state = CASE WHEN downloaded_bytes > 0 THEN 'failed' ELSE 'discovered' END,
                       error = 'Interrupted candidate recovered at restart', updated_at = ?
                   WHERE run_id = ? AND state IN ('downloading', 'downloaded', 'validating')""",
                (_now(), run_id),
            )
        return cursor.rowcount

    def record_download(self, candidate_id: str, byte_size: int) -> None:
        with self.catalog.connect() as connection:
            row = connection.execute(
                """SELECT run_id, downloaded_bytes FROM acquisition_candidates
                   WHERE id = ?""",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Acquisition candidate not found: {candidate_id}")
            previous_bytes = int(row["downloaded_bytes"])
            connection.execute(
                """UPDATE acquisition_candidates SET state = 'downloaded', downloaded_bytes = ?,
                   updated_at = ? WHERE id = ?""",
                (byte_size, _now(), candidate_id),
            )
            connection.execute(
                """UPDATE acquisition_runs
                   SET downloaded_count = downloaded_count + ?,
                       bytes_downloaded = bytes_downloaded + ?, updated_at = ? WHERE id = ?""",
                (
                    int(previous_bytes == 0),
                    max(0, byte_size - previous_bytes),
                    _now(),
                    row["run_id"],
                ),
            )

    def record_candidate_decision(
        self,
        candidate_id: str,
        decision: AcquisitionDecision,
        *,
        sha256: str | None = None,
        asset_id: str | None = None,
        human: bool = False,
    ) -> None:
        state = {
            AcquisitionDecisionKind.ACCEPT: CandidateState.ACCEPTED,
            AcquisitionDecisionKind.REJECT: CandidateState.REJECTED,
            AcquisitionDecisionKind.REVIEW: CandidateState.REVIEW,
        }[decision.decision]
        timestamp = _now()
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT run_id, query_id FROM acquisition_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Acquisition candidate not found: {candidate_id}")
            previous = connection.execute(
                "SELECT state FROM acquisition_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            connection.execute(
                """UPDATE acquisition_candidates SET state = ?,
                   content_sha256 = COALESCE(?, content_sha256),
                   asset_id = COALESCE(?, asset_id), error = NULL, updated_at = ? WHERE id = ?""",
                (state.value, sha256, asset_id, timestamp, candidate_id),
            )
            connection.execute(
                """INSERT INTO acquisition_decisions
                (id, run_id, candidate_id, decision, reason, evaluator_id,
                 evaluator_version, scores_json, human, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    row["run_id"],
                    candidate_id,
                    decision.decision.value,
                    decision.reason.value,
                    decision.evaluator_id,
                    decision.evaluator_version,
                    _json(decision.scores),
                    int(human),
                    timestamp,
                ),
            )
            if row["query_id"] and str(previous["state"]) not in {"accepted", "rejected", "review"}:
                connection.execute(
                    """UPDATE acquisition_queries SET evaluated_count = evaluated_count + 1,
                       accepted_count = accepted_count + ?, updated_at = ? WHERE id = ?""",
                    (
                        int(decision.decision is AcquisitionDecisionKind.ACCEPT),
                        timestamp,
                        row["query_id"],
                    ),
                )

    def record_candidate_failure(self, candidate_id: str, error: Exception) -> None:
        timestamp = _now()
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM acquisition_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Acquisition candidate not found: {candidate_id}")
            connection.execute(
                """INSERT INTO acquisition_decisions
                (id, run_id, candidate_id, decision, reason, evaluator_id,
                 evaluator_version, scores_json, human, created_at)
                VALUES (?, ?, ?, 'reject', 'download_failed', 'downloader',
                        '1.0.0', ?, 0, ?)""",
                (
                    str(uuid4()),
                    row["run_id"],
                    candidate_id,
                    _json({"error": _safe_error(str(error))}),
                    timestamp,
                ),
            )

    def counts(self, run_id: str) -> dict[str, Any]:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT state, COUNT(*) AS count FROM acquisition_candidates
                   WHERE run_id = ? GROUP BY state""",
                (run_id,),
            ).fetchall()
            run = connection.execute(
                """SELECT target_count, downloaded_count, bytes_downloaded,
                   request_count, cycle_count FROM acquisition_runs WHERE id = ?""",
                (run_id,),
            ).fetchone()
            stored = connection.execute(
                """SELECT COALESCE(SUM(downloaded_bytes), 0) AS bytes_stored
                   FROM acquisition_candidates WHERE run_id = ?
                   AND state IN ('accepted', 'review')""",
                (run_id,),
            ).fetchone()
        if run is None:
            raise KeyError(f"Acquisition run not found: {run_id}")
        states = {str(row["state"]): int(row["count"]) for row in rows}
        accepted, rejected = states.get("accepted", 0), states.get("rejected", 0)
        review, failed = states.get("review", 0), states.get("failed", 0)
        evaluated, discovered = accepted + rejected + review, sum(states.values())
        target = int(run["target_count"])
        return {
            "discovered_count": discovered,
            "downloaded_count": int(run["downloaded_count"]),
            "evaluated_count": evaluated,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "review_count": review,
            "failed_count": failed,
            "remaining_count": max(0, target - accepted),
            "observed_yield": accepted / evaluated if evaluated else 0.0,
            "bytes_downloaded": int(run["bytes_downloaded"]),
            "bytes_stored": int(stored["bytes_stored"] if stored else 0),
            "request_count": int(run["request_count"]),
            "cycle_count": int(run["cycle_count"]),
        }

    def update_cycle(self, run_id: str, next_batch_size: int) -> None:
        counts = self.counts(run_id)
        with self.catalog.connect() as connection:
            connection.execute(
                """UPDATE acquisition_runs SET cycle_count = cycle_count + 1,
                   observed_yield = ?, next_batch_size = ?, updated_at = ? WHERE id = ?""",
                (counts["observed_yield"], next_batch_size, _now(), run_id),
            )

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT * FROM acquisition_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Acquisition candidate not found: {candidate_id}")
        return _candidate_row(row)

    def list_candidates(
        self,
        run_id: str,
        *,
        state: str | None = None,
        reason: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        predicates = ["c.run_id = ?"]
        parameters: list[Any] = [run_id]
        if state:
            predicates.append("c.state = ?")
            parameters.append(state)
        if reason:
            predicates.append(
                "EXISTS (SELECT 1 FROM acquisition_decisions d "
                "WHERE d.candidate_id = c.id AND d.reason = ?)"
            )
            parameters.append(reason)
        parameters.append(max(1, min(limit, 5000)))
        query = f"""SELECT c.* FROM acquisition_candidates c
                    WHERE {" AND ".join(predicates)}
                    ORDER BY c.created_at, c.id LIMIT ?"""
        with self.catalog.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_candidate_row(row) for row in rows]

    def rejection_summary(self, run_id: str) -> list[dict[str, Any]]:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT reason, COUNT(*) AS count FROM acquisition_decisions
                   WHERE run_id = ? AND decision = 'reject'
                   GROUP BY reason ORDER BY count DESC, reason""",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def project_policy(self, project_id: str) -> str:
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT data_policy FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return str(row["data_policy"])

    def existing_asset(self, project_id: str, sha256: str) -> dict[str, Any] | None:
        with self.catalog.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE project_id = ? AND sha256 = ? LIMIT 1",
                (project_id, sha256),
            ).fetchone()
        return dict(row) if row else None

    def near_duplicate(
        self, project_id: str, perceptual_hash: str, threshold: int
    ) -> dict[str, Any] | None:
        with self.catalog.connect() as connection:
            rows = connection.execute(
                """SELECT a.id, a.sha256, ia.perceptual_hash FROM assets a
                   JOIN image_analysis ia ON ia.sha256 = a.sha256
                   WHERE a.project_id = ? AND a.state = 'active'
                   AND ia.perceptual_hash IS NOT NULL""",
                (project_id,),
            ).fetchall()
        for row in rows:
            distance = phash_distance(perceptual_hash, str(row["perceptual_hash"]))
            if distance <= threshold:
                return {**dict(row), "distance": distance}
        return None

    def create_candidate_source(self, candidate: dict[str, Any]) -> str:
        source_id = str(uuid4())
        with self.catalog.connect() as connection:
            connection.execute(
                """INSERT INTO sources
                (id, project_id, kind, uri, revision, metadata_json, created_at)
                SELECT ?, r.project_id, ?, ?, NULL, ?, ? FROM acquisition_runs r WHERE r.id = ?""",
                (
                    source_id,
                    f"acquisition:{candidate['provider_id']}",
                    candidate["source_url"],
                    _json(
                        {
                            "remote_id": candidate["remote_id"],
                            "landing_page_url": candidate.get("landing_page_url"),
                            "author": candidate.get("author"),
                            "license": candidate.get("license"),
                            "retrieved_at": _now(),
                        }
                    ),
                    _now(),
                    candidate["run_id"],
                ),
            )
        return source_id

    def set_asset_state(self, asset_id: str, state: str) -> None:
        with self.catalog.connect() as connection:
            cursor = connection.execute(
                "UPDATE assets SET state = ? WHERE id = ?", (state, asset_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Asset not found: {asset_id}")


def _candidate_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = json.loads(str(result.pop("metadata_json") or "{}"))
    return result


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    message = value
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "KAGGLE_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return re.sub(
        r"(?i)(authorization|token|api[_-]?key)(\s*[=:]\s*)([^\s&,;]+)",
        r"\1\2[redacted]",
        message,
    )[:2000]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _now() -> str:
    return datetime.now(UTC).isoformat()
