"""Verify API and worker restart using an isolated temporary workspace."""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="mediasensei-restart-") as directory:
        env = {**os.environ, "MEDIASENSEI_WORKSPACE": str(Path(directory) / "workspace")}
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}/api/v1"
        process = None
        with (Path(directory) / "api.log").open("wb") as log, httpx.Client(timeout=20) as client:

            def start():
                nonlocal process
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "apps.api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Persistence API exited during startup")
                    try:
                        if client.get(url + "/health").is_success:
                            return
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError("Persistence API did not become ready")

            def stop():
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)

            def drain():
                code = "import os; from mediasensei.infrastructure.catalog import Catalog; from mediasensei.infrastructure.jobs import JobQueue; from mediasensei.infrastructure.worker import LocalWorker; w=LocalWorker(JobQueue(Catalog(os.environ['MEDIASENSEI_WORKSPACE'])));\nwhile w.run_once() is not None: pass"
                subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=ROOT,
                    env=env,
                    check=True,
                    timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )

            try:
                start()
                r = client.post(url + "/projects", json={"name": "Restart acceptance"})
                r.raise_for_status()
                project = r.json()["id"]
                model = client.post(
                    url + "/integrations/models/import",
                    json={
                        "format": "mediasensei-fitted-v1",
                        "name": "Restart model",
                        "model": {"kind": "tfidf", "vocabulary": ["forest"], "idf": [1.0]},
                        "training": {"snapshot_sha256": "a" * 64, "sources": []},
                    },
                )
                model.raise_for_status()
                revision = model.json()["revision"]
                script = client.post(
                    url + f"/integrations/projects/{project}/playground",
                    json={
                        "name": "Restart script",
                        "source": 'data = fill_missing(data, columns=["income"], strategy="mean")',
                    },
                )
                script.raise_for_status()
                image = io.BytesIO()
                Image.new("RGB", (80, 60), "red").save(image, "PNG")
                r = client.post(
                    url + f"/projects/{project}/assets",
                    files={"file": ("restart.png", image.getvalue(), "image/png")},
                )
                r.raise_for_status()
                asset = r.json()["asset"]["id"]
                stop()
                drain()
                start()
                r = client.post(
                    url + f"/lab/projects/{project}/asset-operations",
                    json={
                        "operation": "image.edit",
                        "asset_ids": [asset],
                        "parameters": {"width": 24, "height": 24},
                    },
                )
                r.raise_for_status()
                stop()
                drain()
                start()
                outputs = client.get(url + f"/lab/projects/{project}/asset-outputs").json()["items"]
                assert len(outputs) == 1
                link = url + f"/lab/asset-outputs/{outputs[0]['id']}/download"
                before = client.get(link)
                before.raise_for_status()
                # ZIP timestamps can differ: compare the immutable artifact bytes directly.
                artifact_url = url + f"/lab/asset-outputs/{outputs[0]['id']}/artifacts/0"
                digest = hashlib.sha256(client.get(artifact_url).content).hexdigest()
                stop()
                start()
                assert (
                    client.get(url + f"/lab/projects/{project}/asset-outputs").json()["items"]
                    == outputs
                )
                assert hashlib.sha256(client.get(artifact_url).content).hexdigest() == digest
                jobs = client.get(url + f"/jobs?project_id={project}").json()["items"]
                assert jobs and all(job["state"] == "completed" for job in jobs)
                verified = client.get(url + f"/integrations/models/{revision}")
                verified.raise_for_status()
                assert verified.json()["artifact"] == model.json()["artifact"]
                integrations = client.get(url + f"/integrations/projects/{project}")
                integrations.raise_for_status()
                assert integrations.json()["scripts"][0]["id"] == script.json()["id"]
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "checks": [
                                "queued import survives API exit",
                                "worker processes persisted import",
                                "queued transform survives API exit",
                                "new worker completes transform",
                                "outputs and hashes survive API restart",
                                "completed jobs survive restart",
                                "model revision and checksum survive API restart",
                                "saved Playground source survives API restart",
                            ],
                        }
                    )
                )
            finally:
                stop()


if __name__ == "__main__":
    main()
