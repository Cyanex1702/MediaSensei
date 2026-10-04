from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.multimodal import BatchService
from PIL import Image
from test_real_app_flow import _client, _drain_worker

import apps.api.main as api_module


def asset(catalog, tmp_path, filename, payload, modality):
    source = tmp_path / filename
    source.write_bytes(payload)
    stored = ContentAddressedStore(catalog.workspace).import_file(source)
    project = catalog.create_project("Batch 2")
    identifier = catalog.record_asset(
        project_id=str(project.id),
        sha256=stored.sha256,
        original_filename=filename,
        media_type=modality,
        object_key=stored.object_key,
        byte_size=stored.byte_size,
    )
    return str(project.id), identifier, stored


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "TIFF", "BMP"])
def test_image_preview_is_read_only_and_transform_roundtrips(tmp_path, fmt):
    catalog = Catalog(tmp_path / "workspace")
    raw = io.BytesIO()
    Image.new("RGB", (96, 64), "red").save(raw, "PNG")
    project, identifier, stored = asset(catalog, tmp_path, "image.png", raw.getvalue(), "image")
    service = BatchService(catalog)
    p = {
        "width": 40,
        "height": 30,
        "fit": "pad",
        "format": fmt,
        "crop": "10,10,80,60",
        "rotate": 90,
        "flip": "horizontal",
        "mode": "grayscale",
        "brightness": 1.2,
        "contrast": 1.1,
        "sharpness": 1.4,
        "blur": 0.5,
        "normalize": True,
    }
    preview = service.preview(identifier, "image.edit", p)
    assert preview["report"]["width"] == 40
    assert service.outputs(project) == []
    result = service.execute(identifier, "image.edit", p)
    with Image.open(service.store.resolve(result["artifacts"][0]["object_key"])) as im:
        assert im.size == (40, 30)
        assert im.format == fmt
    assert stored.path.read_bytes() == raw.getvalue()
    assert result["provenance"]["source_sha256"] == stored.sha256


def test_image_bad_crop_and_large_output_rejected(tmp_path):
    catalog = Catalog(tmp_path / "workspace")
    raw = io.BytesIO()
    Image.new("RGB", (64, 64)).save(raw, "PNG")
    _, identifier, _ = asset(catalog, tmp_path, "test.png", raw.getvalue(), "image")
    service = BatchService(catalog)
    for p in ({"crop": "0,0,999,999"}, {"width": 16384, "height": 16384}, {"width": float("nan")}):
        with pytest.raises(ValueError):
            service.preview(identifier, "image.edit", p)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "TIFF"])
def test_image_metadata_removed_by_default_and_retained_only_on_request(tmp_path, fmt):
    catalog = Catalog(tmp_path / "workspace")
    raw = io.BytesIO()
    im = Image.new("RGB", (64, 64), "red")
    exif = Image.Exif()
    exif[315] = "Private photographer"
    exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0)}
    im.save(raw, "JPEG", exif=exif)
    _, identifier, _ = asset(catalog, tmp_path, "private.jpg", raw.getvalue(), "image")
    service = BatchService(catalog)
    for strip in (True, False):
        result = service.execute(identifier, "image.edit", {"format": fmt, "strip_metadata": strip})
        with Image.open(service.store.resolve(result["artifacts"][0]["object_key"])) as output:
            assert (315 in output.getexif()) is (not strip)
            assert (34853 in output.getexif()) is (not strip)


@pytest.mark.parametrize("strategy", ["token", "paragraph", "heading", "recursive"])
def test_document_strategies_preserve_punctuation_and_provenance(tmp_path, strategy):
    catalog = Catalog(tmp_path / "workspace")
    raw = (
        "# Introduction\n\nHello, world! The fox is red. "
        + ("This is a sentence, with punctuation! " * 80)
        + "\n\n## Second\n\nOther facts: 42."
    ).encode()
    project, identifier, _ = asset(catalog, tmp_path, "document.md", raw, "document")
    service = BatchService(catalog)
    result = service.execute(
        identifier, "document.prepare", {"strategy": strategy, "chunk_size": 64, "overlap": 8}
    )
    chunks = result["report"]["chunks"]
    assert chunks and all(c["locator"]["token_count"] <= 64 for c in chunks)
    assert any("Hello, world!" in c["text"] for c in chunks)
    assert all(c["asset_id"] == identifier for c in chunks)
    assert catalog.document_index(identifier)["chunking"]["strategy"] == strategy
    bundle = tmp_path / "rag.zip"
    manifest = service.rag_bundle(project, bundle)
    with zipfile.ZipFile(bundle) as z:
        assert {
            "chunks.jsonl",
            "embeddings.jsonl",
            "index-metadata.json",
            "retrieval-config.json",
            "dataset-card.md",
            "provenance.json",
            "manifest.json",
            "checksums.sha256",
        } <= set(z.namelist())
        assert len(z.read("chunks.jsonl").splitlines()) == manifest["chunks"]
        for line in z.read("checksums.sha256").decode().splitlines():
            digest, name = line.split("  ", 1)
            assert hashlib.sha256(z.read(name)).hexdigest() == digest
        assert z.read(manifest["documents"][0]["path"]) == raw


def test_document_regex_cleanup_and_overlap_validation(tmp_path):
    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(
        catalog,
        tmp_path,
        "test.html",
        b"<h1>Title</h1><script>secret</script><p>The fox 123 jumps.</p>",
        "document",
    )
    service = BatchService(catalog)
    p = {"regex": True, "find": "[0-9]+", "replace": "NUMBER", "overlap": 0}
    r = service.preview(identifier, "document.prepare", p)
    assert "NUMBER" in r["report"]["chunks"][0]["text"]
    assert "secret" not in str(r)
    with pytest.raises(ValueError):
        service.preview(identifier, "document.prepare", {"chunk_size": 32, "overlap": 32})
    with pytest.raises(ValueError):
        service.preview(identifier, "document.prepare", {"regex": True, "find": "(?=bad)"})


def test_rag_export_uses_one_snapshot_during_asset_state_change(tmp_path, monkeypatch):
    from contextlib import contextmanager

    catalog = Catalog(tmp_path / "workspace")
    project, identifier, _ = asset(
        catalog, tmp_path, "notes.md", b"A red fox in the forest.", "document"
    )
    service = BatchService(catalog)
    service.execute(identifier, "document.prepare", {})
    connect = catalog.connect
    changed = False

    class Connection:
        def __init__(self, db):
            self.db = db

        def execute(self, sql, values=()):
            nonlocal changed
            cursor = self.db.execute(sql, values)
            if sql.startswith("SELECT * FROM assets") and not changed:
                changed = True
                with connect() as writer:
                    writer.execute("UPDATE assets SET state='excluded' WHERE id=?", (identifier,))
            return cursor

    @contextmanager
    def concurrent_connect():
        with connect() as db:
            yield Connection(db)

    monkeypatch.setattr(catalog, "connect", concurrent_connect)
    bundle = tmp_path / "snapshot.zip"
    manifest = service.rag_bundle(project, bundle)
    assert changed and manifest["chunks"] > 0
    assert manifest["documents"][0]["id"] == identifier
    with zipfile.ZipFile(bundle) as exported:
        assert exported.read(manifest["documents"][0]["path"]) == b"A red fox in the forest."


def test_batch_queue_download_and_project_isolation(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "Batch 2 API"}).json()["id"]
    raw = io.BytesIO()
    Image.new("RGB", (100, 80), "green").save(raw, "PNG")
    imported = client.post(
        f"/api/v1/projects/{project}/assets",
        files={"file": ("green.png", raw.getvalue(), "image/png")},
    )
    assert imported.status_code == 202, imported.text
    _drain_worker()
    identifier = client.get(f"/api/v1/projects/{project}/assets").json()["items"][0]["id"]
    r = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "image.edit",
            "asset_ids": [identifier],
            "parameters": {"width": 32, "height": 32},
        },
    )
    assert r.status_code == 202, r.text
    _drain_worker()
    out = client.get(f"/api/v1/lab/projects/{project}/asset-outputs").json()["items"]
    assert len(out) == 1, client.get("/api/v1/jobs").text
    zipped = client.get(f"/api/v1/lab/asset-outputs/{out[0]['id']}/download")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as z:
        assert "transformed.jpeg" in z.namelist()
    other = client.post("/api/v1/projects", json={"name": "Other"}).json()["id"]
    assert (
        client.post(
            f"/api/v1/lab/projects/{other}/asset-operations",
            json={"operation": "image.edit", "asset_ids": [identifier]},
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/lab/asset-outputs/{out[0]['id']}/artifacts/-1").status_code == 404


def test_acquisition_plan_consent_and_filters_roundtrip(tmp_path):
    client = _client(tmp_path)
    from mediasensei.infrastructure.acquisition import AcquisitionService

    api_module.acquisition = AcquisitionService(api_module.catalog)
    project = client.post("/api/v1/projects", json={"name": "Acquisition"}).json()["id"]
    r = client.post(
        f"/api/v1/projects/{project}/acquisition/plans",
        json={
            "topic": "foxes",
            "target_count": 4,
            "allowed_licenses": ["CC0"],
            "allowed_domains": ["example.org"],
        },
    )
    assert r.status_code == 201, r.text
    p = r.json()["plan"]
    assert p["spec"]["allowed_licenses"] == ["cc0"]
    assert (
        client.post(
            f"/api/v1/acquisition/plans/{p['id']}/start", json={"allow_remote": False}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/acquisition/plans/{p['id']}/start", json={"allow_remote": True}
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/lab/projects/{project}/acquisition-runs").json()["items"] == []
    assert (
        client.post(
            f"/api/v1/lab/projects/{project}/acquisition-consent", json={"allow_remote": True}
        ).json()["data_policy"]
        == "approved_external"
    )
    assert (
        client.post(
            f"/api/v1/lab/projects/{project}/acquisition-consent", json={"allow_remote": False}
        ).json()["data_policy"]
        == "local_only"
    )


@pytest.fixture(scope="module")
def native_media(tmp_path_factory):
    import subprocess
    import wave

    import numpy as np
    from mediasensei.infrastructure.media import FFmpegToolchain

    tools = FFmpegToolchain()
    if not tools.available():
        pytest.skip("FFmpeg and ffprobe are required for native media QA")
    directory = tmp_path_factory.mktemp("native-media")
    audio = directory / "signal.wav"
    rate = 16000
    t = np.arange(rate * 2) / rate
    samples = np.concatenate(
        [np.zeros(rate // 2), np.sin(t * 2 * np.pi * 440) * 0.4, np.zeros(rate // 2)]
    )
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((samples * 32767).astype("<i2").tobytes())
    video = directory / "scene.mp4"
    subprocess.run(
        [
            tools.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:size=160x120:rate=12:duration=1.5",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=160x120:rate=12:duration=1.5",
            "-i",
            str(audio),
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-threads",
            "1",
            "-y",
            str(video),
        ],
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return audio, video


@pytest.mark.parametrize(
    "action",
    [
        "inspect",
        "thumbnail",
        "trim",
        "transcode",
        "frames",
        "contact_sheet",
        "scenes",
        "extract_audio",
    ],
)
def test_native_video_actions(tmp_path, native_media, action):
    from mediasensei.infrastructure.media import FFmpegToolchain

    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(catalog, tmp_path, "scene.mp4", native_media[1].read_bytes(), "video")
    service = BatchService(catalog)
    result = service.execute(
        identifier,
        "video.process",
        {
            "action": action,
            "count": 4,
            "width": 160,
            "height": 120,
            "fps": 6,
            "scene_threshold": 0.1,
        },
    )
    if action == "scenes":
        assert result["report"]["actual_frames"] >= 1
    elif action == "frames":
        assert result["report"]["actual_frames"] == 4
    elif action != "inspect":
        assert result["artifacts"]
    for output in result["artifacts"]:
        path = service.store.resolve(output["object_key"])
        assert path.stat().st_size > 0
        if output["mime"].startswith("video/"):
            info = FFmpegToolchain().probe(path)
            stream = next(s for s in info["streams"] if s["codec_type"] == "video")
            assert stream["width"] <= 160
            assert stream["avg_frame_rate"] == "6/1"


@pytest.mark.parametrize(
    "action",
    [
        "inspect",
        "trim",
        "convert",
        "resample",
        "channels",
        "normalize",
        "silence",
        "remove_silence",
        "segment",
        "waveform",
        "spectrogram",
        "features",
    ],
)
def test_native_audio_actions(tmp_path, native_media, action):
    from mediasensei.infrastructure.media import FFmpegToolchain

    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(catalog, tmp_path, "signal.wav", native_media[0].read_bytes(), "audio")
    service = BatchService(catalog)
    result = service.execute(
        identifier,
        "audio.process",
        {"action": action, "sample_rate": 22050, "channels": "2", "segment_seconds": 1},
    )
    if action == "silence":
        assert len(result["report"]["silence_intervals"]) >= 2
    elif action == "features":
        assert result["report"]["features"]
    elif action != "inspect":
        assert result["artifacts"]
    for output in result["artifacts"]:
        path = service.store.resolve(output["object_key"])
        assert path.stat().st_size > 0
        if output["mime"].startswith("audio/"):
            info = FFmpegToolchain().probe(path)
            assert int(info["streams"][0]["sample_rate"]) == 22050
            assert info["streams"][0]["channels"] == 2
            if action == "remove_silence":
                assert float(info["format"]["duration"]) < 2.3


def test_media_sampling_limits_and_trim_bounds(tmp_path, native_media):
    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(catalog, tmp_path, "scene.mp4", native_media[1].read_bytes(), "video")
    service = BatchService(catalog)
    with pytest.raises(ValueError):
        service.preview(identifier, "video.process", {"sampling": "seconds", "interval": 0.001})
    with pytest.raises(ValueError):
        service.preview(identifier, "video.process", {"sampling": "frames", "interval": 1.5})
    with pytest.raises(ValueError):
        service.preview(identifier, "video.process", {"start": 10})
    result = service.execute(
        identifier,
        "video.process",
        {"action": "frames", "sampling": "frames", "interval": 12, "width": 160},
    )
    assert result["report"]["actual_frames"] == 3


@pytest.mark.parametrize("fmt", ["mp3", "flac", "ogg"])
def test_native_audio_output_formats(tmp_path, native_media, fmt):
    from mediasensei.infrastructure.media import FFmpegToolchain

    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(catalog, tmp_path, "signal.wav", native_media[0].read_bytes(), "audio")
    service = BatchService(catalog)
    r = service.execute(identifier, "audio.process", {"action": "convert", "format": fmt})
    assert r["artifacts"][0]["mime"].startswith("audio/")
    probe = FFmpegToolchain().probe(service.store.resolve(r["artifacts"][0]["object_key"]))
    assert int(probe["streams"][0]["sample_rate"]) == (48000 if fmt == "ogg" else 44100)


def test_native_video_webm_and_clip_duration(tmp_path, native_media):
    from mediasensei.infrastructure.media import FFmpegToolchain

    catalog = Catalog(tmp_path / "workspace")
    _, identifier, _ = asset(catalog, tmp_path, "scene.mp4", native_media[1].read_bytes(), "video")
    service = BatchService(catalog)
    r = service.execute(
        identifier,
        "video.process",
        {
            "action": "trim",
            "format": "webm",
            "start": 1,
            "duration": 1,
            "width": 160,
            "height": 120,
        },
    )
    probe = FFmpegToolchain().probe(service.store.resolve(r["artifacts"][0]["object_key"]))
    assert 0.9 < float(probe["format"]["duration"]) < 1.2


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows inbox OCR is Windows-only")
def test_windows_ocr_recognizes_text_and_regions(tmp_path):
    from mediasensei.infrastructure.windows_ocr import WindowsOCRProvider
    from PIL import ImageDraw, ImageFont

    im = Image.new("RGB", (800, 180), "white")
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
    draw.text((30, 45), "MediaSensei OCR test 123", font=font, fill="black")
    file = tmp_path / "ocr.png"
    im.save(file)
    result = WindowsOCRProvider().recognize(file, language="eng")
    assert "MediaSensei" in result.text and "123" in result.text
    assert len(result.regions) >= 4
    assert result.confidence is None
