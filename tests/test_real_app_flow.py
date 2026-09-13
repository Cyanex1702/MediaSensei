from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.infrastructure.worker import LocalWorker
from PIL import Image

import apps.api.main as api_module


def _client(tmp_path: Path) -> TestClient:
    api_module.WORKSPACE = tmp_path / "workspace"
    api_module.catalog = Catalog(api_module.WORKSPACE)
    api_module.store = ContentAddressedStore(api_module.WORKSPACE)
    api_module.queue = JobQueue(api_module.catalog)
    return TestClient(api_module.app)


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 64), "white").save(output, format="PNG")
    return output.getvalue()


def _drain_worker() -> None:
    from mediasensei.infrastructure.scheduler import HardwareProfile
    worker = LocalWorker(api_module.queue, hardware=HardwareProfile(4, 8 * 1024**3, 4 * 1024**3, 20 * 1024**3))
    while worker.run_once() is not None:
        pass


def test_real_image_upload_job_and_thumbnail(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "Real flow"}).json()
    project_id = project["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["asset"]["original_filename"] == "photo.png"
    assert payload["jobs"][0]["kind"] == "image-inspection"

    _drain_worker()
    assets = client.get(f"/api/v1/projects/{project_id}/assets").json()["items"]
    assert len(assets) == 1
    assert assets[0]["analysis"]["valid"] is True
    assert assets[0]["thumbnail_available"] is True

    thumbnail = client.get(f"/api/v1/assets/{assets[0]['id']}/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/webp")
    assert thumbnail.content


def test_zip_import_is_real_and_blocks_traversal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = client.post("/api/v1/projects", json={"name": "ZIP flow"}).json()["id"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("images/one.png", _png_bytes())
        bundle.writestr("../escape.png", _png_bytes())
        bundle.writestr("notes.unsupported", b"ignored")
    archive.seek(0)

    response = client.post(
        f"/api/v1/projects/{project_id}/imports/archive",
        files={"file": ("dataset.zip", archive.getvalue(), "application/zip")},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["skipped_count"] == 2
    assert any(item["reason"] == "unsafe path" for item in payload["skipped"])

    _drain_worker()
    assets = client.get(f"/api/v1/projects/{project_id}/assets").json()["items"]
    assert [asset["original_filename"] for asset in assets] == ["one.png"]
    assert assets[0]["thumbnail_available"] is True


def test_upload_to_missing_project_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/projects/does-not-exist/assets",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_document_upload_indexes_and_searches_real_text(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = client.post("/api/v1/projects", json={"name": "Docs"}).json()["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={
            "file": (
                "field-notes.txt",
                b"Night cameras recorded urban foxes near the river after midnight.",
                "text/plain",
            )
        },
    )
    assert response.status_code == 202
    assert response.json()["jobs"][0]["kind"] == "document-index"
    _drain_worker()

    result = client.post(
        f"/api/v1/projects/{project_id}/documents/search",
        json={"query": "fox cameras at night", "asset_ids": [], "limit": 5, "minimum_score": 0},
    )
    assert result.status_code == 200
    payload = result.json()
    assert payload["items"]
    assert "fox" in payload["items"][0]["text"].lower()


def test_catalog_assets_survive_catalog_reopen(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = client.post("/api/v1/projects", json={"name": "Persistence"}).json()["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("persistent.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 202
    _drain_worker()

    reopened = Catalog(api_module.WORKSPACE)
    rows = reopened.list_assets(project_id, state=None)
    assert len(rows) == 1
    assert rows[0]["original_filename"] == "persistent.png"
    assert reopened.image_analysis(str(rows[0]["sha256"])) is not None


def test_missing_project_list_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/projects/missing/images")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_image_transform_is_downloadable_and_asset_state_is_real(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = client.post("/api/v1/projects", json={"name": "Derived"}).json()["id"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    ).json()
    asset_id = upload["asset"]["id"]
    _drain_worker()

    transform = client.post(
        f"/api/v1/projects/{project_id}/images/transform",
        json={
            "asset_ids": [asset_id],
            "width": 32,
            "height": 32,
            "fit": "contain",
            "format": "JPEG",
            "quality": 90,
            "background": "#000000",
        },
    )
    assert transform.status_code == 202
    _drain_worker()
    asset = client.get(f"/api/v1/projects/{project_id}/assets").json()["items"][0]
    transforms = [item for item in asset["derivatives"] if item["kind"] == "transform"]
    assert transforms
    download = client.get(f"/api/v1/derived/images/{transforms[0]['id']}/content")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/jpeg")

    quarantined = client.patch(f"/api/v1/assets/{asset_id}", json={"state": "quarantined"})
    assert quarantined.status_code == 200
    assert quarantined.json()["state"] == "quarantined"
    reactivated = client.patch(f"/api/v1/assets/{asset_id}", json={"state": "active"})
    assert reactivated.status_code == 200
    assert reactivated.json()["state"] == "active"


def test_media_import_and_derivative_are_real_when_ffmpeg_available(tmp_path: Path) -> None:
    import math
    import shutil
    import struct
    import wave

    import pytest

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg is not installed")

    client = _client(tmp_path)
    project_id = client.post("/api/v1/projects", json={"name": "Media"}).json()["id"]
    audio = io.BytesIO()
    with wave.open(audio, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
                for i in range(8000)
            )
        )
    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("tone.wav", audio.getvalue(), "audio/wav")},
    )
    assert response.status_code == 202
    asset_id = response.json()["asset"]["id"]
    _drain_worker()
    asset = client.get(f"/api/v1/projects/{project_id}/assets").json()["items"][0]
    assert asset["analysis"]["valid"] is True

    derive = client.post(
        f"/api/v1/projects/{project_id}/media/derive",
        json={"asset_ids": [asset_id], "kind": "transcode", "format": "mp3"},
    )
    assert derive.status_code == 202
    _drain_worker()
    media = client.get(f"/api/v1/projects/{project_id}/media").json()["items"][0]
    transcodes = [item for item in media["derivatives"] if item["kind"] == "transcode"]
    assert transcodes
    download = client.get(f"/api/v1/derived/media/{transcodes[0]['id']}/content")
    assert download.status_code == 200
    assert download.content
