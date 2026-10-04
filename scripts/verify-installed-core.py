"""Run outside the checkout with a clean, non-editable wheel installation."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import mediasensei
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.worker import LocalWorker
from mediasensei.integrations import IntegrationService
from mediasensei.native_adapters import installed_voices


def main():
    installed = Path(mediasensei.__file__).resolve()
    assert "site-packages" in installed.parts, installed
    assert installed.with_name("native_speech.ps1").is_file()
    with tempfile.TemporaryDirectory(prefix="mediasensei-wheel-") as folder:
        catalog = Catalog(Path(folder) / "workspace")
        project = str(catalog.create_project("Installed wheel acceptance").id)
        service = IntegrationService(catalog)
        # Use the same persisted snapshot and processor path as API-queued training.
        job = service.enqueue(
            project,
            "model.train",
            {
                "name": "Wheel model",
                "kind": "tfidf",
                "texts": ["forest fox", "red fox"],
                "labels": [],
                "sources": [],
            },
        )
        worker = LocalWorker(JobQueue(catalog))
        while worker.run_once() is not None:
            pass
        assert JobQueue(catalog).get(job["job_id"]).state.value == "completed"
        model = service.models()[0]
        raw = service.store.resolve(model["object_key"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == model["revision"]
        provider = service.embedding(model["revision"])
        assert any(provider.embed(["forest"])[0])
        assert (
            IntegrationService(Catalog(catalog.workspace)).models()[0]["revision"]
            == model["revision"]
        )
        voice_count = len(installed_voices())
        print(
            json.dumps(
                {
                    "ok": True,
                    "version": mediasensei.__version__,
                    "python": sys.executable,
                    "installed_module": str(installed),
                    "native_voices": voice_count,
                    "checks": [
                        "non-editable wheel import outside checkout",
                        "bundled speech adapter",
                        "durable worker training",
                        "model checksum and fitted inference",
                        "catalog reopen",
                        "native adapter invocation",
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
