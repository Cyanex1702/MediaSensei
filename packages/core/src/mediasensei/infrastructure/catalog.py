from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from mediasensei.domain.documents import ChunkEmbedding, DocumentAnalysis, DocumentChunk
from mediasensei.domain.images import (
    DatasetSample,
    DerivedImage,
    ExportResult,
    ImageAnalysis,
    LeakageIssue,
    OCRAction,
)
from mediasensei.domain.media import DerivedMedia, MediaAnalysis
from mediasensei.domain.models import Project
from mediasensei.domain.providers import DatasetSnapshot, ProviderFile
from mediasensei.domain.tabular import TabularAnalysis, TabularExportResult

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    data_policy TEXT NOT NULL DEFAULT 'local_only',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    uri TEXT,
    revision TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    source_id TEXT REFERENCES sources(id),
    sha256 TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_project_media ON assets(project_id, media_type);
CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project_state ON jobs(project_id, state);
CREATE TABLE IF NOT EXISTS dataset_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    manifest_hash TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    split_seed INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS image_analysis (
    sha256 TEXT PRIMARY KEY,
    valid INTEGER NOT NULL,
    format TEXT,
    mime_type TEXT,
    width INTEGER,
    height INTEGER,
    color_mode TEXT,
    exif_orientation INTEGER,
    has_alpha INTEGER NOT NULL DEFAULT 0,
    perceptual_hash TEXT,
    blur_score REAL,
    quality_score REAL,
    error TEXT,
    ocr_json TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_image_analysis_phash ON image_analysis(perceptual_hash);
CREATE TABLE IF NOT EXISTS derived_images (
    id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    object_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    parameters_json TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_sha256, kind, parameters_hash)
);
CREATE INDEX IF NOT EXISTS idx_derived_images_source ON derived_images(source_sha256, kind);
CREATE TABLE IF NOT EXISTS content_units (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    kind TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    text_content TEXT,
    parent_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_units_asset_id ON content_units(asset_id);
CREATE TABLE IF NOT EXISTS dataset_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    label TEXT NOT NULL DEFAULT 'unlabeled',
    split TEXT,
    source_key TEXT,
    group_key TEXT,
    split_seed INTEGER,
    split_strategy TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_dataset_samples_project_split
ON dataset_samples(project_id, split);
CREATE TABLE IF NOT EXISTS duplicate_groups (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    method TEXT NOT NULL,
    group_key TEXT NOT NULL,
    canonical_asset_id TEXT REFERENCES assets(id),
    maximum_distance INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_duplicate_groups_project_method
ON duplicate_groups(project_id, method);
CREATE TABLE IF NOT EXISTS duplicate_group_members (
    group_id TEXT NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(id),
    PRIMARY KEY(group_id, asset_id)
);
CREATE TABLE IF NOT EXISTS leakage_issues (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    left_asset_id TEXT NOT NULL REFERENCES assets(id),
    right_asset_id TEXT NOT NULL REFERENCES assets(id),
    left_split TEXT NOT NULL,
    right_split TEXT NOT NULL,
    kind TEXT NOT NULL,
    distance INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, left_asset_id, right_asset_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_leakage_issues_project_kind
ON leakage_issues(project_id, kind);
CREATE TABLE IF NOT EXISTS dataset_exports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    exporter_id TEXT NOT NULL,
    path TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    split_counts_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dataset_exports_project_created
ON dataset_exports(project_id, created_at);
CREATE TABLE IF NOT EXISTS tabular_analysis (
    analysis_key TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    source_format TEXT NOT NULL,
    normalized_sha256 TEXT NOT NULL,
    normalized_object_key TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    schema_json TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tabular_analysis_source
ON tabular_analysis(source_sha256, source_format);
CREATE TABLE IF NOT EXISTS tabular_datasets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    analysis_key TEXT NOT NULL,
    name TEXT NOT NULL,
    schema_mapping_json TEXT NOT NULL DEFAULT '{}',
    custom_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_tabular_datasets_project_created
ON tabular_datasets(project_id, created_at);
CREATE TABLE IF NOT EXISTS tabular_queries (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES tabular_datasets(id) ON DELETE CASCADE,
    query_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tabular_queries_dataset_created
ON tabular_queries(dataset_id, created_at);
CREATE TABLE IF NOT EXISTS tabular_exports (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES tabular_datasets(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tabular_exports_dataset_created
ON tabular_exports(dataset_id, created_at);
CREATE TABLE IF NOT EXISTS document_analysis (
    source_sha256 TEXT PRIMARY KEY,
    document_format TEXT NOT NULL,
    valid INTEGER NOT NULL,
    title TEXT,
    page_count INTEGER,
    block_count INTEGER NOT NULL,
    character_count INTEGER NOT NULL,
    parser_revision TEXT NOT NULL,
    error TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_indexes (
    asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,
    document_format TEXT NOT NULL,
    title TEXT,
    parser_revision TEXT NOT NULL,
    chunking_json TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_indexes_source
ON document_indexes(source_sha256);
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content_unit_id TEXT NOT NULL REFERENCES content_units(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_blob BLOB NOT NULL,
    vector_norm REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(content_unit_id, model_revision)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_project_model
ON embeddings(project_id, model_id, model_revision);
CREATE INDEX IF NOT EXISTS idx_content_units_asset_kind
ON content_units(asset_id, kind);
CREATE TABLE IF NOT EXISTS provider_imports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES sources(id),
    provider_id TEXT NOT NULL,
    provider_version TEXT,
    dataset_id TEXT NOT NULL,
    requested_revision TEXT,
    resolved_revision TEXT,
    source_uri TEXT,
    title TEXT,
    license TEXT,
    state TEXT NOT NULL,
    allow_patterns_json TEXT NOT NULL DEFAULT '[]',
    ignore_patterns_json TEXT NOT NULL DEFAULT '[]',
    max_files INTEGER NOT NULL,
    max_file_bytes INTEGER NOT NULL,
    max_total_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    filtered_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    imported_bytes INTEGER NOT NULL DEFAULT 0,
    manifest_hash TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_imports_project_created
ON provider_imports(project_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_provider_imports_provider_dataset_revision
ON provider_imports(provider_id, dataset_id, resolved_revision);
CREATE TABLE IF NOT EXISTS provider_import_files (
    import_id TEXT NOT NULL REFERENCES provider_imports(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    byte_size INTEGER,
    expected_sha256 TEXT,
    etag TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    asset_id TEXT REFERENCES assets(id),
    actual_sha256 TEXT,
    object_key TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(import_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_provider_import_files_import_state
ON provider_import_files(import_id, state);CREATE TABLE IF NOT EXISTS media_analysis (
    sha256 TEXT PRIMARY KEY,
    valid INTEGER NOT NULL,
    media_kind TEXT NOT NULL,
    container TEXT,
    duration_seconds REAL,
    bit_rate INTEGER,
    size_bytes INTEGER,
    video_codec TEXT,
    width INTEGER,
    height INTEGER,
    fps REAL,
    pixel_format TEXT,
    audio_codec TEXT,
    sample_rate INTEGER,
    channels INTEGER,
    channel_layout TEXT,
    tags_json TEXT NOT NULL DEFAULT '{}',
    tool_revision TEXT,
    error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_analysis_kind_valid
ON media_analysis(media_kind, valid);
CREATE TABLE IF NOT EXISTS derived_media (
    id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    object_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    duration_seconds REAL,
    tool_revision TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(source_sha256, kind, parameters_hash)
);
CREATE INDEX IF NOT EXISTS idx_derived_media_source_kind
ON derived_media(source_sha256, kind);"""


class Catalog:
    """Small restart-safe SQLite catalog used by the API, CLI, and SDK."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        metadata = self.workspace / "metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        self.database_path = metadata / "mediasensei.db"
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA optimize")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_project(
        self, name: str, description: str = "", data_policy: str = "local_only"
    ) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty")
        project = Project(name=clean_name, description=description.strip(), data_policy=data_policy)
        timestamp = project.created_at.isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(project.id),
                    project.name,
                    project.description,
                    project.data_policy,
                    timestamp,
                    timestamp,
                ),
            )
        return project

    def list_projects(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, data_policy, created_at, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT id, name, description, data_policy, created_at, updated_at
                   FROM projects WHERE id = ?""",
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return dict(row)

    def record_asset(
        self,
        *,
        project_id: str,
        source_id: str | None = None,
        sha256: str,
        original_filename: str,
        media_type: str,
        object_key: str,
        byte_size: int,
        metadata: dict[str, object] | None = None,
    ) -> str:
        asset_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO assets
                   (id, project_id, source_id, sha256, original_filename, media_type, object_key,
                    byte_size, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset_id,
                    project_id,
                    source_id,
                    sha256,
                    original_filename,
                    media_type,
                    object_key,
                    byte_size,
                    json.dumps(metadata or {}, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return asset_id

    def get_asset(self, asset_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(f"Asset not found: {asset_id}")
        return _asset_row(row)

    def list_assets(
        self,
        project_id: str,
        *,
        media_type: str | None = None,
        state: str | None = "active",
    ) -> list[dict[str, object]]:
        predicates = ["project_id = ?"]
        parameters: list[object] = [project_id]
        if media_type is not None:
            predicates.append("media_type = ?")
            parameters.append(media_type)
        if state is not None:
            predicates.append("state = ?")
            parameters.append(state)
        query = f"SELECT * FROM assets WHERE {' AND '.join(predicates)} ORDER BY created_at, id"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_asset_row(row) for row in rows]

    def set_asset_state(self, asset_id: str, state: str) -> dict[str, object]:
        if state not in {"active", "quarantined", "excluded"}:
            raise ValueError(f"Invalid asset state: {state}")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE assets SET state = ? WHERE id = ?", (state, asset_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Asset not found: {asset_id}")
        return self.get_asset(asset_id)

    def set_asset_state_by_sha256(self, sha256: str, state: str) -> int:
        if state not in {"active", "quarantined", "excluded"}:
            raise ValueError(f"Invalid asset state: {state}")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE assets SET state = ? WHERE sha256 = ?", (state, sha256)
            )
        return cursor.rowcount

    def upsert_image_analysis(self, analysis: ImageAnalysis) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO image_analysis (
                    sha256, valid, format, mime_type, width, height, color_mode,
                    exif_orientation, has_alpha, perceptual_hash, blur_score,
                    quality_score, error, ocr_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    valid=excluded.valid, format=excluded.format, mime_type=excluded.mime_type,
                    width=excluded.width, height=excluded.height, color_mode=excluded.color_mode,
                    exif_orientation=excluded.exif_orientation, has_alpha=excluded.has_alpha,
                    perceptual_hash=excluded.perceptual_hash, blur_score=excluded.blur_score,
                    quality_score=excluded.quality_score, error=excluded.error,
                    ocr_json=COALESCE(excluded.ocr_json, image_analysis.ocr_json),
                    updated_at=excluded.updated_at""",
                (
                    analysis.sha256,
                    int(analysis.valid),
                    analysis.format,
                    analysis.mime_type,
                    analysis.width,
                    analysis.height,
                    analysis.color_mode,
                    analysis.exif_orientation,
                    int(analysis.has_alpha),
                    analysis.perceptual_hash,
                    analysis.blur_score,
                    analysis.quality_score,
                    analysis.error,
                    json.dumps(analysis.ocr, sort_keys=True) if analysis.ocr else None,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def image_analysis(self, sha256: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM image_analysis WHERE sha256 = ?", (sha256,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["valid"] = bool(result["valid"])
        result["has_alpha"] = bool(result["has_alpha"])
        ocr_json = result.pop("ocr_json")
        result["ocr"] = json.loads(str(ocr_json)) if ocr_json else None
        return result

    def record_derived_image(self, derived: DerivedImage) -> str:
        parameters_json = json.dumps(derived.parameters, sort_keys=True, separators=(",", ":"))
        parameters_hash = hashlib.sha256(parameters_json.encode()).hexdigest()
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT id FROM derived_images
                   WHERE source_sha256 = ? AND kind = ? AND parameters_hash = ?""",
                (derived.source_sha256, derived.kind, parameters_hash),
            ).fetchone()
            if existing:
                return str(existing["id"])
            derived_id = str(uuid4())
            connection.execute(
                """INSERT INTO derived_images VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    derived_id,
                    derived.source_sha256,
                    derived.sha256,
                    derived.object_key,
                    derived.kind,
                    derived.format,
                    derived.width,
                    derived.height,
                    parameters_json,
                    parameters_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return derived_id

    def derived_images(self, source_sha256: str, *, kind: str | None = None) -> list[dict[str, object]]:
        predicates = ["source_sha256 = ?"]
        parameters: list[object] = [source_sha256]
        if kind is not None:
            predicates.append("kind = ?")
            parameters.append(kind)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM derived_images WHERE {' AND '.join(predicates)} ORDER BY created_at DESC",
                parameters,
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("parameters_json", "{}")
            item["parameters"] = json.loads(str(raw)) if raw else {}
            results.append(item)
        return results

    def get_derived_image(self, derived_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM derived_images WHERE id = ?", (derived_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Derived image not found: {derived_id}")
        item = dict(row)
        raw = item.pop("parameters_json", "{}")
        item["parameters"] = json.loads(str(raw)) if raw else {}
        return item

    def apply_ocr_action(self, sha256: str, ocr: dict[str, object], action: OCRAction) -> None:
        if action == OCRAction.QUARANTINE and str(ocr.get("text", "")).strip():
            self.set_asset_state_by_sha256(sha256, "quarantined")
        if action != OCRAction.STORE_TEXT or not str(ocr.get("text", "")).strip():
            return
        with self.connect() as connection:
            assets = connection.execute(
                "SELECT id FROM assets WHERE sha256 = ?", (sha256,)
            ).fetchall()
            for asset in assets:
                connection.execute(
                    """INSERT INTO content_units
                       (id, asset_id, kind, locator_json, text_content, created_at)
                       VALUES (?, ?, 'ocr_block', ?, ?, ?)""",
                    (
                        str(uuid4()),
                        asset["id"],
                        json.dumps({"regions": ocr.get("regions", [])}, sort_keys=True),
                        str(ocr.get("text", "")),
                        datetime.now(UTC).isoformat(),
                    ),
                )

    def replace_dataset_samples(
        self,
        project_id: str,
        samples: list[DatasetSample],
        *,
        seed: int,
        strategy: str,
    ) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute("DELETE FROM dataset_samples WHERE project_id = ?", (project_id,))
            connection.executemany(
                """INSERT INTO dataset_samples
                   (id, project_id, asset_id, label, split, source_key, group_key,
                    split_seed, split_strategy, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        str(uuid4()),
                        project_id,
                        sample.asset_id,
                        sample.label,
                        sample.split,
                        sample.source_key,
                        sample.group_key,
                        seed,
                        strategy,
                        timestamp,
                        timestamp,
                    )
                    for sample in samples
                ],
            )

    def dataset_samples(self, project_id: str) -> list[DatasetSample]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT ds.asset_id, a.sha256, a.object_key, a.original_filename,
                          ds.label, ds.source_key, ds.group_key, ds.split,
                          ia.perceptual_hash
                   FROM dataset_samples ds
                   JOIN assets a ON a.id = ds.asset_id
                   LEFT JOIN image_analysis ia ON ia.sha256 = a.sha256
                   WHERE ds.project_id = ? ORDER BY ds.asset_id""",
                (project_id,),
            ).fetchall()
        return [
            DatasetSample(
                asset_id=str(row["asset_id"]),
                sha256=str(row["sha256"]),
                object_key=str(row["object_key"]),
                filename=str(row["original_filename"]),
                label=str(row["label"]),
                source_key=row["source_key"],
                group_key=row["group_key"],
                perceptual_hash=row["perceptual_hash"],
                split=row["split"],
            )
            for row in rows
        ]

    def replace_duplicate_groups(self, project_id: str, groups: list[dict[str, object]]) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM duplicate_groups WHERE project_id = ?", (project_id,)
            ).fetchall()
            for row in existing:
                connection.execute(
                    "DELETE FROM duplicate_group_members WHERE group_id = ?", (row["id"],)
                )
            connection.execute("DELETE FROM duplicate_groups WHERE project_id = ?", (project_id,))
            for group in groups:
                group_id = str(uuid4())
                connection.execute(
                    """INSERT INTO duplicate_groups VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        group_id,
                        project_id,
                        group["method"],
                        group["key"],
                        group["canonical_asset_id"],
                        group["maximum_distance"],
                        datetime.now(UTC).isoformat(),
                    ),
                )
                connection.executemany(
                    "INSERT INTO duplicate_group_members VALUES (?, ?)",
                    [(group_id, asset_id) for asset_id in cast(list[str], group["asset_ids"])],
                )

    def replace_leakage_issues(self, project_id: str, issues: list[LeakageIssue]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM leakage_issues WHERE project_id = ?", (project_id,))
            connection.executemany(
                """INSERT INTO leakage_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        str(uuid4()),
                        project_id,
                        issue.left_asset_id,
                        issue.right_asset_id,
                        issue.left_split,
                        issue.right_split,
                        issue.kind,
                        issue.distance,
                        datetime.now(UTC).isoformat(),
                    )
                    for issue in issues
                ],
            )

    def upsert_tabular_analysis(self, analysis: TabularAnalysis) -> None:
        schema = [
            {"name": column.name, "type": column.arrow_type} for column in analysis.profile.columns
        ]
        profile = {
            "row_count": analysis.profile.row_count,
            "column_count": analysis.profile.column_count,
            "columns": [
                {
                    "name": column.name,
                    "arrow_type": column.arrow_type,
                    "null_count": column.null_count,
                    "distinct_count": column.distinct_count,
                    "minimum": column.minimum,
                    "maximum": column.maximum,
                    "mean": column.mean,
                    "frequencies": list(column.frequencies),
                }
                for column in analysis.profile.columns
            ],
            "sample": list(analysis.profile.sample),
        }
        timestamp = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO tabular_analysis (
                    analysis_key, source_sha256, source_format, normalized_sha256,
                    normalized_object_key, row_count, column_count, schema_json,
                    profile_json, options_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(analysis_key) DO UPDATE SET
                    normalized_sha256=excluded.normalized_sha256,
                    normalized_object_key=excluded.normalized_object_key,
                    row_count=excluded.row_count, column_count=excluded.column_count,
                    schema_json=excluded.schema_json, profile_json=excluded.profile_json,
                    options_json=excluded.options_json, updated_at=excluded.updated_at""",
                (
                    analysis.analysis_key,
                    analysis.source_sha256,
                    analysis.source_format.value,
                    analysis.normalized_sha256,
                    analysis.normalized_object_key,
                    analysis.profile.row_count,
                    analysis.profile.column_count,
                    json.dumps(schema, sort_keys=True, default=str),
                    json.dumps(profile, sort_keys=True, default=str),
                    json.dumps(analysis.options, sort_keys=True),
                    timestamp,
                ),
            )

    def record_tabular_dataset(
        self,
        *,
        project_id: str,
        asset_id: str,
        analysis_key: str,
        name: str,
    ) -> str:
        timestamp = datetime.now(UTC).isoformat()
        dataset_id = str(uuid4())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM tabular_datasets WHERE project_id = ? AND asset_id = ?",
                (project_id, asset_id),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE tabular_datasets SET analysis_key = ?, name = ?, updated_at = ?
                       WHERE id = ?""",
                    (analysis_key, name.strip() or "Untitled table", timestamp, existing["id"]),
                )
                return str(existing["id"])
            connection.execute(
                """INSERT INTO tabular_datasets
                   (id, project_id, asset_id, analysis_key, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    dataset_id,
                    project_id,
                    asset_id,
                    analysis_key,
                    name.strip() or "Untitled table",
                    timestamp,
                    timestamp,
                ),
            )
        return dataset_id

    def get_tabular_dataset(self, dataset_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT td.*, a.source_sha256, a.source_format, a.normalized_sha256,
                          a.normalized_object_key, a.row_count, a.column_count,
                          a.schema_json, a.profile_json, a.options_json
                   FROM tabular_datasets td
                   JOIN tabular_analysis a ON a.analysis_key = td.analysis_key
                   WHERE td.id = ?""",
                (dataset_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Tabular dataset not found or not yet inspected: {dataset_id}")
        return _tabular_row(row)

    def list_tabular_datasets(self, project_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT td.*, a.source_sha256, a.source_format, a.normalized_sha256,
                          a.normalized_object_key, a.row_count, a.column_count,
                          a.schema_json, a.profile_json, a.options_json
                   FROM tabular_datasets td
                   LEFT JOIN tabular_analysis a ON a.analysis_key = td.analysis_key
                   WHERE td.project_id = ? ORDER BY td.created_at DESC""",
                (project_id,),
            ).fetchall()
        return [_tabular_row(row) for row in rows]

    def update_tabular_mapping(
        self,
        dataset_id: str,
        *,
        schema_mapping: dict[str, str],
        custom_metadata: dict[str, object],
    ) -> dict[str, object]:
        clean_mapping = {
            str(source).strip(): str(target).strip()
            for source, target in schema_mapping.items()
            if str(source).strip() and str(target).strip()
        }
        dataset = self.get_tabular_dataset(dataset_id)
        schema = dataset.get("schema", [])
        if not isinstance(schema, list):
            schema = []
        available = {
            str(column.get("name"))
            for column in schema
            if isinstance(column, dict) and column.get("name")
        }
        unknown = sorted(set(clean_mapping) - available)
        if unknown:
            raise ValueError(f"Unknown mapped source column(s): {','.join(unknown)}")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE tabular_datasets SET schema_mapping_json = ?,
                   custom_metadata_json = ?, updated_at = ? WHERE id = ?""",
                (
                    json.dumps(clean_mapping, sort_keys=True),
                    json.dumps(custom_metadata, sort_keys=True, default=str),
                    datetime.now(UTC).isoformat(),
                    dataset_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Tabular dataset not found: {dataset_id}")
        return self.get_tabular_dataset(dataset_id)

    def record_tabular_query(
        self, dataset_id: str, query: dict[str, object], row_count: int, duration_ms: float
    ) -> str:
        query_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tabular_queries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    query_id,
                    dataset_id,
                    json.dumps(query, sort_keys=True, default=str),
                    row_count,
                    duration_ms,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return query_id

    def record_tabular_export(self, dataset_id: str, result: TabularExportResult) -> str:
        export_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tabular_exports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    export_id,
                    dataset_id,
                    result.format.value,
                    result.path,
                    result.sha256,
                    result.row_count,
                    result.column_count,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return export_id

    def upsert_document_analysis(self, analysis: DocumentAnalysis) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO document_analysis (
                    source_sha256, document_format, valid, title, page_count,
                    block_count, character_count, parser_revision, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_sha256) DO UPDATE SET
                    document_format=excluded.document_format, valid=excluded.valid,
                    title=excluded.title, page_count=excluded.page_count,
                    block_count=excluded.block_count,
                    character_count=excluded.character_count,
                    parser_revision=excluded.parser_revision, error=excluded.error,
                    updated_at=excluded.updated_at""",
                (
                    analysis.source_sha256,
                    analysis.document_format.value,
                    int(analysis.valid),
                    analysis.title,
                    analysis.page_count,
                    analysis.block_count,
                    analysis.character_count,
                    analysis.parser_revision,
                    analysis.error,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def replace_document_index(
        self,
        *,
        asset_id: str,
        analysis: DocumentAnalysis,
        chunks: list[DocumentChunk],
        embeddings: list[ChunkEmbedding],
        options: dict[str, object],
    ) -> None:
        if len(chunks) != len(embeddings) or not chunks:
            raise ValueError("Document chunks and embeddings must be non-empty and aligned")
        if any(chunk.asset_id != asset_id for chunk in chunks):
            raise ValueError("Every document chunk must belong to the indexed asset")
        timestamp = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            asset = connection.execute(
                "SELECT project_id FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if asset is None:
                raise KeyError(f"Asset not found: {asset_id}")
            connection.execute(
                """INSERT INTO document_analysis (
                    source_sha256, document_format, valid, title, page_count,
                    block_count, character_count, parser_revision, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_sha256) DO UPDATE SET
                    document_format=excluded.document_format, valid=excluded.valid,
                    title=excluded.title, page_count=excluded.page_count,
                    block_count=excluded.block_count,
                    character_count=excluded.character_count,
                    parser_revision=excluded.parser_revision, error=excluded.error,
                    updated_at=excluded.updated_at""",
                (
                    analysis.source_sha256,
                    analysis.document_format.value,
                    int(analysis.valid),
                    analysis.title,
                    analysis.page_count,
                    analysis.block_count,
                    analysis.character_count,
                    analysis.parser_revision,
                    analysis.error,
                    timestamp,
                ),
            )
            connection.execute(
                """DELETE FROM embeddings WHERE content_unit_id IN (
                    SELECT id FROM content_units WHERE asset_id = ? AND kind = 'document_chunk'
                )""",
                (asset_id,),
            )
            connection.execute(
                "DELETE FROM content_units WHERE asset_id = ? AND kind = 'document_chunk'",
                (asset_id,),
            )
            for chunk, embedding in zip(chunks, embeddings):
                if chunk.id != embedding.content_unit_id:
                    raise ValueError("Embedding content-unit identity does not match its chunk")
                connection.execute(
                    """INSERT INTO content_units
                       (id, asset_id, kind, locator_json, text_content, parent_id, created_at)
                       VALUES (?, ?, 'document_chunk', ?, ?, NULL, ?)""",
                    (
                        chunk.id,
                        asset_id,
                        json.dumps(
                            {
                                **chunk.locator,
                                "sequence": chunk.sequence,
                                "word_count": chunk.word_count,
                                "content_hash": chunk.content_hash,
                            },
                            sort_keys=True,
                        ),
                        chunk.text,
                        timestamp,
                    ),
                )
                vector_blob = _pack_vector(embedding.vector)
                vector_norm = sum(value * value for value in embedding.vector) ** 0.5
                connection.execute(
                    """INSERT INTO embeddings (
                        id, project_id, content_unit_id, source_sha256, model_id,
                        model_revision, dimensions, vector_blob, vector_norm, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        asset["project_id"],
                        embedding.content_unit_id,
                        embedding.source_sha256,
                        embedding.model_id,
                        embedding.model_revision,
                        embedding.dimensions,
                        vector_blob,
                        vector_norm,
                        timestamp,
                    ),
                )
            first = embeddings[0]
            connection.execute(
                """INSERT INTO document_indexes (
                    asset_id, source_sha256, document_format, title, parser_revision,
                    chunking_json, model_id, model_revision, dimensions, chunk_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    source_sha256=excluded.source_sha256,
                    document_format=excluded.document_format, title=excluded.title,
                    parser_revision=excluded.parser_revision,
                    chunking_json=excluded.chunking_json, model_id=excluded.model_id,
                    model_revision=excluded.model_revision, dimensions=excluded.dimensions,
                    chunk_count=excluded.chunk_count, updated_at=excluded.updated_at""",
                (
                    asset_id,
                    analysis.source_sha256,
                    analysis.document_format.value,
                    analysis.title,
                    analysis.parser_revision,
                    json.dumps(options, sort_keys=True),
                    first.model_id,
                    first.model_revision,
                    first.dimensions,
                    len(chunks),
                    timestamp,
                ),
            )

    def document_analysis(self, source_sha256: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM document_analysis WHERE source_sha256 = ?",
                (source_sha256,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["valid"] = bool(result["valid"])
        return result

    def document_index(self, asset_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM document_indexes WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        value = result.pop("chunking_json", None)
        result["chunking"] = json.loads(str(value)) if value else {}
        return result

    def document_chunks(self, asset_id: str, *, limit: int = 200) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id, asset_id, locator_json, text_content, created_at
                   FROM content_units
                   WHERE asset_id = ? AND kind = 'document_chunk'
                   ORDER BY CAST(json_extract(locator_json, '$.sequence') AS INTEGER), id
                   LIMIT ?""",
                (asset_id, max(1, min(limit, 1000))),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            result = dict(row)
            value = result.pop("locator_json", None)
            result["locator"] = json.loads(str(value)) if value else {}
            results.append(result)
        return results

    def list_document_indexes(self, project_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT a.*, di.title, di.document_format, di.parser_revision,
                          di.chunking_json, di.model_id, di.model_revision,
                          di.dimensions, di.chunk_count, di.updated_at AS indexed_at
                   FROM assets a
                   LEFT JOIN document_indexes di ON di.asset_id = a.id
                   WHERE a.project_id = ? AND a.media_type = 'document'
                   ORDER BY a.created_at, a.id""",
                (project_id,),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            result = _asset_row(row)
            value = result.pop("chunking_json", None)
            result["chunking"] = json.loads(str(value)) if value else None
            results.append(result)
        return results

    def embedding_candidates(
        self,
        project_id: str,
        *,
        model_id: str,
        model_revision: str,
        asset_ids: list[str],
    ) -> list[dict[str, object]]:
        if len(asset_ids) > 500:
            raise ValueError("Retrieval filters support at most 500 asset ids")
        predicates = [
            "e.project_id = ?",
            "e.model_id = ?",
            "e.model_revision = ?",
            "a.state = 'active'",
        ]
        parameters: list[object] = [project_id, model_id, model_revision]
        if asset_ids:
            predicates.append(f"a.id IN ({','.join('?' for _ in asset_ids)})")
            parameters.extend(asset_ids)
        query = f"""SELECT e.content_unit_id, e.dimensions, e.vector_blob,
                           cu.asset_id, cu.text_content, cu.locator_json,
                           a.original_filename, di.title
                    FROM embeddings e
                    JOIN content_units cu ON cu.id = e.content_unit_id
                    JOIN assets a ON a.id = cu.asset_id
                    LEFT JOIN document_indexes di ON di.asset_id = a.id
                    WHERE {" AND ".join(predicates)}
                    LIMIT 100000"""
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def document_stats(self, project_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS documents,
                          COALESCE(SUM(chunk_count), 0) AS chunks,
                          COALESCE(MAX(dimensions), 0) AS dimensions,
                          MAX(model_id) AS model_id,
                          MAX(model_revision) AS model_revision
                   FROM document_indexes di
                   JOIN assets a ON a.id = di.asset_id
                   WHERE a.project_id = ? AND a.state = 'active'""",
                (project_id,),
            ).fetchone()
        return (
            dict(row)
            if row is not None
            else {
                "documents": 0,
                "chunks": 0,
                "dimensions": 0,
                "model_id": None,
                "model_revision": None,
            }
        )

    def create_provider_import(
        self,
        *,
        project_id: str,
        provider_id: str,
        dataset_id: str,
        requested_revision: str | None,
        allow_patterns: tuple[str, ...],
        ignore_patterns: tuple[str, ...],
        max_files: int,
        max_file_bytes: int,
        max_total_bytes: int,
    ) -> str:
        import_id = str(uuid4())
        timestamp = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise KeyError(f"Project not found: {project_id}")
            connection.execute(
                """INSERT INTO provider_imports (
                    id, project_id, provider_id, dataset_id, requested_revision, state,
                    allow_patterns_json, ignore_patterns_json, max_files, max_file_bytes,
                    max_total_bytes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    project_id,
                    provider_id,
                    dataset_id,
                    requested_revision,
                    json.dumps(allow_patterns),
                    json.dumps(ignore_patterns),
                    max_files,
                    max_file_bytes,
                    max_total_bytes,
                    timestamp,
                    timestamp,
                ),
            )
        return import_id

    def provider_import(self, import_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_imports WHERE id = ?", (import_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Provider import not found: {import_id}")
        return _provider_import_row(row)

    def list_provider_imports(self, project_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM provider_imports
                   WHERE project_id = ? ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
        return [_provider_import_row(row) for row in rows]

    def set_provider_import_state(
        self, import_id: str, state: str, error: str | None = None
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE provider_imports SET state = ?, error = ?, updated_at = ?
                   WHERE id = ?""",
                (state, error[:2000] if error else None, datetime.now(UTC).isoformat(), import_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Provider import not found: {import_id}")

    def resolve_provider_import(
        self,
        import_id: str,
        *,
        snapshot: DatasetSnapshot,
        files: tuple[ProviderFile, ...],
        manifest_hash: str,
        filtered_count: int,
    ) -> str:
        timestamp = datetime.now(UTC).isoformat()
        provider_id = str(snapshot.provider_id)
        dataset_id = str(snapshot.dataset_id)
        resolved_revision = str(snapshot.resolved_revision)
        source_uri = str(snapshot.source_uri)
        source_id = str(uuid4())
        with self.connect() as connection:
            current = connection.execute(
                "SELECT project_id, source_id FROM provider_imports WHERE id = ?", (import_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"Provider import not found: {import_id}")
            if current["source_id"]:
                source_id = str(current["source_id"])
            else:
                connection.execute(
                    """INSERT INTO sources
                       (id, project_id, kind, uri, revision, metadata_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        current["project_id"],
                        f"dataset_provider:{provider_id}",
                        source_uri,
                        resolved_revision,
                        json.dumps(
                            {
                                "provider_id": provider_id,
                                "provider_version": str(snapshot.provider_version),
                                "dataset_id": dataset_id,
                                "requested_revision": snapshot.requested_revision,
                                "title": snapshot.title,
                                "license": snapshot.license,
                            },
                            sort_keys=True,
                        ),
                        timestamp,
                    ),
                )
            connection.execute(
                """UPDATE provider_imports SET source_id = ?, provider_version = ?,
                   resolved_revision = ?, source_uri = ?, title = ?, license = ?,
                   state = 'importing', file_count = ?, filtered_count = ?,
                   manifest_hash = ?, metadata_json = ?, error = NULL, updated_at = ?
                   WHERE id = ?""",
                (
                    source_id,
                    str(snapshot.provider_version),
                    resolved_revision,
                    source_uri,
                    snapshot.title,
                    snapshot.license,
                    len(files),
                    filtered_count,
                    manifest_hash,
                    json.dumps(snapshot.metadata, sort_keys=True, default=str),
                    timestamp,
                    import_id,
                ),
            )
            for item in files:
                connection.execute(
                    """INSERT INTO provider_import_files (
                        import_id, relative_path, byte_size, expected_sha256, etag,
                        state, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    ON CONFLICT(import_id, relative_path) DO UPDATE SET
                        byte_size=excluded.byte_size,
                        expected_sha256=excluded.expected_sha256,
                        etag=excluded.etag,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at""",
                    (
                        import_id,
                        str(item.path),
                        item.byte_size,
                        item.sha256,
                        item.etag,
                        json.dumps(item.metadata, sort_keys=True, default=str),
                        timestamp,
                        timestamp,
                    ),
                )
        return source_id

    def provider_import_files(
        self, import_id: str, *, incomplete_only: bool = False
    ) -> list[dict[str, object]]:
        predicate = "AND state NOT IN ('completed', 'skipped')" if incomplete_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM provider_import_files WHERE import_id = ? {predicate}
                    ORDER BY relative_path""",
                (import_id,),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            result = dict(row)
            metadata = result.pop("metadata_json", None)
            result["metadata"] = json.loads(str(metadata)) if metadata else {}
            results.append(result)
        return results

    def start_provider_import_file(self, import_id: str, relative_path: str) -> None:
        self._set_provider_file_state(import_id, relative_path, "importing", error=None)

    def fail_provider_import_file(self, import_id: str, relative_path: str, error: str) -> None:
        self._set_provider_file_state(import_id, relative_path, "failed", error=error)

    def skip_provider_import_file(self, import_id: str, relative_path: str, reason: str) -> None:
        self._set_provider_file_state(import_id, relative_path, "skipped", error=reason)

    def _set_provider_file_state(
        self, import_id: str, relative_path: str, state: str, *, error: str | None
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE provider_import_files SET state = ?, error = ?, updated_at = ?
                   WHERE import_id = ? AND relative_path = ?""",
                (
                    state,
                    error[:2000] if error else None,
                    datetime.now(UTC).isoformat(),
                    import_id,
                    relative_path,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Provider import file not found: {relative_path}")

    def complete_provider_import_file(
        self,
        import_id: str,
        relative_path: str,
        *,
        asset_id: str,
        actual_sha256: str,
        object_key: str,
        byte_size: int,
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE provider_import_files SET state = 'completed', asset_id = ?,
                   actual_sha256 = ?, object_key = ?, byte_size = ?, error = NULL,
                   updated_at = ? WHERE import_id = ? AND relative_path = ?""",
                (
                    asset_id,
                    actual_sha256,
                    object_key,
                    byte_size,
                    datetime.now(UTC).isoformat(),
                    import_id,
                    relative_path,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Provider import file not found: {relative_path}")

    def provider_import_file_counts(self, import_id: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT state, COUNT(*) AS count,
                          COALESCE(SUM(CASE WHEN state = 'completed' THEN byte_size ELSE 0 END), 0)
                          AS imported_bytes
                   FROM provider_import_files WHERE import_id = ? GROUP BY state""",
                (import_id,),
            ).fetchall()
        result = {
            "pending": 0,
            "importing": 0,
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "imported_bytes": 0,
        }
        for row in rows:
            result[str(row["state"])] = int(row["count"])
            result["imported_bytes"] += int(row["imported_bytes"])
        return result

    def finalize_provider_import(self, import_id: str, state: str, manifest_hash: str) -> None:
        counts = self.provider_import_file_counts(import_id)
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE provider_imports SET state = ?, imported_count = ?,
                   skipped_count = ?, failed_count = ?, imported_bytes = ?,
                   manifest_hash = ?, error = CASE WHEN ? = 0 THEN NULL ELSE error END,
                   updated_at = ? WHERE id = ?""",
                (
                    state,
                    counts["completed"],
                    counts["skipped"],
                    counts["failed"],
                    counts["imported_bytes"],
                    manifest_hash,
                    counts["failed"],
                    datetime.now(UTC).isoformat(),
                    import_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Provider import not found: {import_id}")

    def upsert_media_analysis(self, analysis: MediaAnalysis) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO media_analysis (
                    sha256, valid, media_kind, container, duration_seconds, bit_rate,
                    size_bytes, video_codec, width, height, fps, pixel_format,
                    audio_codec, sample_rate, channels, channel_layout, tags_json,
                    tool_revision, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    valid=excluded.valid, media_kind=excluded.media_kind,
                    container=excluded.container, duration_seconds=excluded.duration_seconds,
                    bit_rate=excluded.bit_rate, size_bytes=excluded.size_bytes,
                    video_codec=excluded.video_codec, width=excluded.width,
                    height=excluded.height, fps=excluded.fps,
                    pixel_format=excluded.pixel_format, audio_codec=excluded.audio_codec,
                    sample_rate=excluded.sample_rate, channels=excluded.channels,
                    channel_layout=excluded.channel_layout, tags_json=excluded.tags_json,
                    tool_revision=excluded.tool_revision, error=excluded.error,
                    updated_at=excluded.updated_at""",
                (
                    analysis.sha256,
                    int(analysis.valid),
                    analysis.media_kind.value,
                    analysis.container,
                    analysis.duration_seconds,
                    analysis.bit_rate,
                    analysis.size_bytes,
                    analysis.video_codec,
                    analysis.width,
                    analysis.height,
                    analysis.fps,
                    analysis.pixel_format,
                    analysis.audio_codec,
                    analysis.sample_rate,
                    analysis.channels,
                    analysis.channel_layout,
                    json.dumps(analysis.tags, sort_keys=True),
                    analysis.tool_revision,
                    analysis.error,
                    timestamp,
                ),
            )

    def media_analysis(self, sha256: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM media_analysis WHERE sha256 = ?", (sha256,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["valid"] = bool(result["valid"])
        value = result.pop("tags_json", None)
        result["tags"] = json.loads(str(value)) if value else {}
        return result

    def record_derived_media(self, derived: DerivedMedia) -> str:
        parameters_json = json.dumps(derived.parameters, sort_keys=True, default=str)
        parameters_hash = hashlib.sha256(parameters_json.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT id FROM derived_media
                   WHERE source_sha256 = ? AND kind = ? AND parameters_hash = ?""",
                (derived.source_sha256, derived.kind.value, parameters_hash),
            ).fetchone()
            if existing:
                return str(existing["id"])
            derived_id = str(uuid4())
            connection.execute(
                """INSERT INTO derived_media (
                    id, source_sha256, sha256, object_key, kind, format, mime_type,
                    parameters_json, parameters_hash, duration_seconds, tool_revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    derived_id,
                    derived.source_sha256,
                    derived.sha256,
                    derived.object_key,
                    derived.kind.value,
                    derived.format,
                    derived.mime_type,
                    parameters_json,
                    parameters_hash,
                    derived.duration_seconds,
                    derived.tool_revision,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return derived_id

    def derived_media(self, source_sha256: str, kind: str | None = None) -> list[dict[str, object]]:
        sql = "SELECT * FROM derived_media WHERE source_sha256 = ?"
        parameters: tuple[object, ...] = (source_sha256,)
        if kind is not None:
            sql += " AND kind = ?"
            parameters += (kind,)
        sql += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            result = dict(row)
            value = result.pop("parameters_json", None)
            result["parameters"] = json.loads(str(value)) if value else {}
            results.append(result)
        return results

    def get_derived_media(self, derived_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM derived_media WHERE id = ?", (derived_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Derived media not found: {derived_id}")
        item = dict(row)
        raw = item.pop("parameters_json", "{}")
        item["parameters"] = json.loads(str(raw)) if raw else {}
        return item

    def list_dataset_exports(self, project_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dataset_exports WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["split_counts"] = json.loads(str(item.pop("split_counts_json", "{}")))
            results.append(item)
        return results

    def get_dataset_export(self, export_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_exports WHERE id = ?", (export_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Dataset export not found: {export_id}")
        item = dict(row)
        item["split_counts"] = json.loads(str(item.pop("split_counts_json", "{}")))
        return item

    def get_tabular_export(self, export_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tabular_exports WHERE id = ?", (export_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Tabular export not found: {export_id}")
        return dict(row)

    def record_export(self, project_id: str, result: ExportResult) -> str:
        export_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO dataset_exports VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    export_id,
                    project_id,
                    "media-parquet",
                    result.path,
                    result.manifest_hash,
                    result.sample_count,
                    json.dumps(result.split_counts, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return export_id


def _pack_vector(vector: tuple[float, ...]) -> bytes:
    import struct

    return struct.pack(f"<{len(vector)}f", *vector)


def _tabular_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    for source, target in (
        ("schema_json", "schema"),
        ("profile_json", "profile"),
        ("options_json", "options"),
        ("schema_mapping_json", "schema_mapping"),
        ("custom_metadata_json", "custom_metadata"),
    ):
        value = result.pop(source, None)
        result[target] = json.loads(str(value)) if value else {}
    return result


def _provider_import_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    for source, target in (
        ("allow_patterns_json", "allow_patterns"),
        ("ignore_patterns_json", "ignore_patterns"),
        ("metadata_json", "metadata"),
    ):
        value = result.pop(source, None)
        result[target] = json.loads(str(value)) if value else ([] if "patterns" in target else {})
    return result


def _asset_row(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    result["metadata"] = json.loads(str(result.pop("metadata_json")))
    return result
