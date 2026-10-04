"""Revision-pinned integrations using the existing catalog, object store and workers."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from mediasensei.domain.jobs import ProcessorSpec, WorkItem
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.learned import (
    FittedEmbeddingProvider,
    classify_language,
    fit_model,
    validate_model,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_revisions (
 revision TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
 object_key TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS saved_connections (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS playground_scripts (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 name TEXT NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS playground_project ON playground_scripts(project_id,created_at);
CREATE TABLE IF NOT EXISTS voice_personalities (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, voice TEXT NOT NULL, rate INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def now():
    return datetime.now(UTC).isoformat()


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("A name between 1 and 120 characters is required.")
    return value.strip()


class CredentialVault:
    def __init__(self, workspace):
        self.service = (
            "MediaSensei/" + hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()
        )

    def backend(self):
        try:
            import keyring

            backend = keyring.get_keyring()
            module = type(backend).__module__
            if module not in {
                "keyring.backends.Windows",
                "keyring.backends.macOS",
                "keyring.backends.SecretService",
                "keyring.backends.libsecret",
            }:
                raise ValueError("Unavailable native credential store")
            return backend
        except Exception:  # noqa: BLE001 - native vault errors must never expose credentials
            raise ValueError("The native OS credential store is unavailable or locked.") from None

    def put(self, identifier, secret):
        if not isinstance(secret, str) or not 1 <= len(secret) <= 16384:
            raise ValueError("Provide a nonempty credential of at most 16 KiB.")
        try:
            self.backend().set_password(self.service, identifier, secret)
        except Exception:  # noqa: BLE001 - native vault errors must never expose credentials
            raise ValueError("Could not save the credential in the native OS store.") from None

    def get(self, identifier):
        try:
            secret = self.backend().get_password(self.service, identifier)
        except Exception:  # noqa: BLE001 - native vault errors must never expose credentials
            raise ValueError("Could not read the credential from the native OS store.") from None
        if not secret:
            raise ValueError("Credential is missing; save it again in Connections.")
        return secret

    def delete(self, identifier):
        try:
            backend = self.backend()
            if backend.get_password(self.service, identifier) is not None:
                backend.delete_password(self.service, identifier)
        except Exception:  # noqa: BLE001 - native vault errors must never expose credentials
            raise ValueError(
                "Connection disabled, but its OS credential could not be removed."
            ) from None


class IntegrationService:
    def __init__(self, catalog, *, vault=None):
        self.catalog = catalog
        self.store = ContentAddressedStore(catalog.workspace)
        self.vault = vault or CredentialVault(catalog.workspace)
        with catalog.connect() as db:
            db.executescript(SCHEMA)

    def store_json(self, value):
        data = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        if len(data) > 4 * 1024**2:
            raise ValueError("Integration snapshot exceeds 4 MiB.")
        with tempfile.TemporaryDirectory(dir=self.store.temp_root) as directory:
            path = Path(directory) / "snapshot.json"
            path.write_bytes(data)
            return self.store.import_file(path)

    def enqueue(self, project, operation, payload, *, revision=None):
        self.catalog.get_project(project)
        snapshot = self.store_json(payload)
        job = JobQueue(self.catalog).enqueue(
            project_id=project,
            kind=operation,
            processor=ProcessorSpec(
                operation,
                "1.0.0",
                deterministic=operation != "connection.import",
                cacheable=False,
                model_revision=revision,
            ),
            items=[WorkItem(snapshot.sha256, snapshot.object_key, 0)],
            parameters={"project_id": project},
        )
        return {"job_id": job.id, "operation": operation, "input_sha256": snapshot.sha256}

    def train(self, project, name, kind, asset_ids, labels):
        name = label(name)
        if (
            kind not in {"tfidf", "language"}
            or not isinstance(asset_ids, list)
            or not 1 <= len(asset_ids) <= 100
        ):
            raise ValueError("Select 1–100 indexed documents and a supported model kind.")
        texts, training_labels, sources = [], [], []
        with self.catalog.connect() as db:
            db.execute("BEGIN")
            for identifier in dict.fromkeys(asset_ids):
                asset = db.execute(
                    "SELECT * FROM assets WHERE id=? AND project_id=? AND state='active' AND media_type='document'",
                    (identifier, project),
                ).fetchone()
                if not asset:
                    raise ValueError("Training document is unavailable in this project.")
                chunks = db.execute(
                    "SELECT text_content FROM content_units WHERE asset_id=? AND kind='document_chunk' ORDER BY id LIMIT 1001",
                    (identifier,),
                ).fetchall()
                if not chunks:
                    raise ValueError("Index each training document before training a model.")
                texts.extend(row[0] for row in chunks)
                training_labels.extend([labels.get(identifier, "")] * len(chunks))
                sources.append({"asset_id": identifier, "sha256": asset["sha256"]})
                if len(texts) > 1000 or sum(len(text.encode()) for text in texts) > 2 * 1024**2:
                    raise ValueError("Training exceeds 1000 chunks or 2 MiB.")
        # Validate cheap shape requirements before queueing; fitting runs only in the worker.
        if kind == "language" and (
            len(set(training_labels)) < 2
            or any(
                not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", item) for item in training_labels
            )
        ):
            raise ValueError("Assign at least two language labels to the selected documents.")
        return self.enqueue(
            project,
            "model.train",
            {
                "name": name,
                "kind": kind,
                "texts": texts,
                "labels": training_labels,
                "sources": sources,
            },
        )

    def import_model(self, payload):
        if (
            not isinstance(payload, dict)
            or set(payload) != {"format", "name", "model", "training"}
            or payload["format"] != "mediasensei-fitted-v1"
        ):
            raise ValueError("Import a MediaSensei fitted-model JSON artifact.")
        name = label(payload["name"])
        validate_model(payload["model"])
        training = payload["training"]
        if (
            not isinstance(training, dict)
            or set(training) != {"snapshot_sha256", "sources"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(training["snapshot_sha256"]))
        ):
            raise ValueError("Invalid training provenance.")
        if not isinstance(training["sources"], list) or len(training["sources"]) > 100:
            raise ValueError("Invalid training source count.")
        for source in training["sources"]:
            if (
                not isinstance(source, dict)
                or set(source) != {"asset_id", "sha256"}
                or not re.fullmatch(r"[a-f0-9]{64}", str(source["sha256"]))
                or len(str(source["asset_id"])) > 64
            ):
                raise ValueError("Invalid training source identity.")
        stored = self.store_json(payload)
        with self.catalog.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO model_revisions VALUES (?,?,?,?,0,?)",
                (stored.sha256, name, payload["model"]["kind"], stored.object_key, now()),
            )
        return self.model(stored.sha256)

    def models(self):
        with self.catalog.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM model_revisions ORDER BY created_at DESC")
            ]

    def model(self, revision, *, require_active=False):
        with self.catalog.connect() as db:
            row = db.execute(
                "SELECT * FROM model_revisions WHERE revision=?", (revision,)
            ).fetchone()
        if not row:
            raise KeyError("Model revision not found")
        if require_active and row["archived"]:
            raise ValueError("Model is archived; reactivate it before starting new work.")
        path = self.store.resolve(row["object_key"])
        if path.stat().st_size > 4 * 1024**2:
            raise ValueError("Model artifact exceeds its size limit.")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != revision:
            raise ValueError("Model checksum verification failed.")
        payload = json.loads(raw)
        validate_model(payload["model"])
        return {**dict(row), "artifact": payload}

    def archive_model(self, revision, archived):
        self.model(revision)
        with self.catalog.connect() as db:
            db.execute(
                "UPDATE model_revisions SET archived=? WHERE revision=?", (int(archived), revision)
            )
        return self.model(revision)

    def embedding(self, revision, *, require_active=False):
        return FittedEmbeddingProvider(
            self.model(revision, require_active=require_active)["artifact"]["model"], revision
        )

    def search(self, project, revision, query):
        from mediasensei.infrastructure.documents import SQLiteVectorIndex

        self.catalog.get_project(project)
        return [
            asdict(hit)
            for hit in SQLiteVectorIndex(
                self.catalog, embedding_provider=self.embedding(revision)
            ).search(project, query)
        ]

    def language(self, revision, text):
        model = self.model(revision, require_active=True)
        return {**classify_language(model["artifact"]["model"], text), "model_revision": revision}

    def connections(self):
        with self.catalog.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM saved_connections ORDER BY created_at DESC")
            ]

    def save_connection(self, name, provider, secret):
        name = label(name)
        if provider != "huggingface":
            raise ValueError("This credential adapter supports Hugging Face dataset imports.")
        identifier = str(uuid4())
        self.vault.put(identifier, secret)
        try:
            with self.catalog.connect() as db:
                db.execute(
                    "INSERT INTO saved_connections VALUES (?,?,?,1,?)",
                    (identifier, name, provider, now()),
                )
        except Exception:
            self.vault.delete(identifier)
            raise
        return {"id": identifier, "name": name, "provider": provider, "enabled": True}

    def connection(self, identifier):
        with self.catalog.connect() as db:
            row = db.execute(
                "SELECT * FROM saved_connections WHERE id=? AND enabled=1", (identifier,)
            ).fetchone()
        if not row:
            raise ValueError("Connection is unavailable or revoked.")
        return dict(row)

    def revoke_connection(self, identifier):
        with self.catalog.connect() as db:
            db.execute("UPDATE saved_connections SET enabled=0 WHERE id=?", (identifier,))
        self.vault.delete(identifier)
        return {"revoked": True}

    def queue_import(self, project, connection, dataset, revision, allow_remote):
        from mediasensei.infrastructure.providers import _validate_dataset_id

        if not allow_remote or self.catalog.get_project(project)["data_policy"] == "local_only":
            raise ValueError(
                "Explicit remote consent and an approved external project are required."
            )
        self.connection(connection)
        dataset = _validate_dataset_id(dataset)
        if revision is not None and (
            not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", revision)
        ):
            raise ValueError("Invalid dataset revision.")
        return self.enqueue(
            project,
            "connection.import",
            {"connection_id": connection, "dataset": dataset, "revision": revision},
        )

    def playground(self, project, name, source, *, dataset=None, revision=None, execute=False):
        from mediasensei.operations import Workbench
        from mediasensei.playground import compile_script

        name = label(name)
        self.catalog.get_project(project)
        steps = compile_script(source)
        run = None
        if execute:
            wb = Workbench(self.catalog)
            record = wb.dataset(dataset)
            if record["project_id"] != project:
                raise ValueError("Dataset belongs to another project.")
            run = wb.enqueue(dataset, steps, revision)
        identifier = str(uuid4())
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO playground_scripts VALUES (?,?,?,?,?,?,?)",
                (
                    identifier,
                    project,
                    label(name),
                    source,
                    hashlib.sha256(source.encode()).hexdigest(),
                    run["run_id"] if run else None,
                    now(),
                ),
            )
        return {"id": identifier, "steps": steps, "run": run}

    def scripts(self, project):
        with self.catalog.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM playground_scripts WHERE project_id=? ORDER BY created_at DESC LIMIT 100",
                    (project,),
                )
            ]

    def voices(self):
        with self.catalog.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM voice_personalities ORDER BY created_at DESC")
            ]

    def save_voice(self, name, voice, rate):
        from mediasensei.native_adapters import installed_voices

        if voice not in installed_voices() or type(rate) is not int or not -10 <= rate <= 10:
            raise ValueError("Select an installed local voice and a rate from -10 to 10.")
        identifier = str(uuid4())
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO voice_personalities VALUES (?,?,?,?,?)",
                (identifier, label(name), voice, rate, now()),
            )
        return {"id": identifier, "name": name, "voice": voice, "rate": rate}


def register_integration_processors(registry, catalog):
    service = IntegrationService(catalog)

    def train(item, parameters):
        path = service.store.resolve(item.input_ref)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.input_hash:
            raise ValueError("Training snapshot checksum mismatch.")
        payload = json.loads(raw)
        fitted = fit_model(payload["texts"], payload["kind"], payload["labels"])
        model = service.import_model(
            {
                "format": "mediasensei-fitted-v1",
                "name": payload["name"],
                "model": fitted,
                "training": {"snapshot_sha256": item.input_hash, "sources": payload["sources"]},
            }
        )
        return {key: value for key, value in model.items() if key != "artifact"}

    def connected_import(item, parameters):
        from mediasensei.infrastructure.providers import (
            DatasetProviderRegistry,
            HuggingFaceDatasetProvider,
            ProviderImportService,
            _safe_provider_error,
        )

        project = parameters["project_id"]
        if catalog.get_project(project)["data_policy"] == "local_only":
            raise ValueError("External access was disabled before this import ran.")
        raw = service.store.resolve(item.input_ref).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.input_hash:
            raise ValueError("Provider request checksum mismatch.")
        payload = json.loads(raw)
        service.connection(payload["connection_id"])
        secret = service.vault.get(payload["connection_id"])

        def check_access():
            if catalog.get_project(project)["data_policy"] == "local_only":
                raise ValueError("External access was disabled during this import.")
            service.connection(payload["connection_id"])

        provider = HuggingFaceDatasetProvider(token=secret)
        if not provider.available():
            raise ValueError("Install the providers extra before importing remote datasets.")
        try:
            import_id = catalog.create_provider_import(
                project_id=project,
                provider_id=provider.provider_id,
                dataset_id=payload["dataset"],
                requested_revision=payload["revision"],
                allow_patterns=(),
                ignore_patterns=(),
                max_files=100,
                max_file_bytes=100 * 1024**2,
                max_total_bytes=512 * 1024**2,
            )
            result = ProviderImportService(
                catalog,
                registry=DatasetProviderRegistry([provider]),
                sensitive_values=(secret,),
                control_check=check_access,
            ).execute(import_id)
            return asdict(result)
        except Exception as error:  # noqa: BLE001 - redact provider credentials before persistence
            raise ValueError(_safe_provider_error(error, (secret,))) from None

    registry.register("model.train", train)
    registry.register("connection.import", connected_import)
