from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.integrations import IntegrationService

spec = importlib.util.spec_from_file_location(
    "release_certification", Path(__file__).resolve().parents[1] / "scripts/release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize("platform", release.PLATFORMS)
def test_release_rebuild_is_byte_identical_and_private_state_is_excluded(
    tmp_path, monkeypatch, platform
):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1788998400")
    first = release.build_bundle(platform, tmp_path / "one")
    second = release.build_bundle(platform, tmp_path / "two")
    assert first.read_bytes() == second.read_bytes()
    report = release.verify_bundle(first)
    assert report["valid"] and report["version"] == release.project_version()
    names = release._archive_entries(first)
    assert any(name.endswith("native_speech.ps1") for name in names)
    assert not any(
        any(
            part in {".audit", ".venv", "outputs", "node_modules", ".env", ".mediasensei-workspace"}
            for part in Path(name).parts
        )
        for name in names
    )
    assert not any(Path(name).suffix in release.SENSITIVE_SUFFIXES for name in names)


def test_release_rejects_tampered_file(tmp_path):
    original = release.build_bundle("windows", tmp_path)
    entries = release._archive_entries(original)
    name = next(name for name in entries if name.endswith("README.md"))
    entries[name] += b"tampered"
    altered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(altered, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    with pytest.raises(release.ReleaseError, match="verification failed"):
        release.verify_bundle(altered)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "root/..\\escape"])
def test_release_rejects_platform_unsafe_paths(tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, b"data")
    with pytest.raises(release.ReleaseError, match="unsafe path"):
        release.verify_bundle(archive)


def test_release_rejects_case_collisions_and_tar_links(tmp_path):
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("root/readme", b"one")
        bundle.writestr("root/README", b"two")
    with pytest.raises(release.ReleaseError, match="duplicate"):
        release.verify_bundle(archive)
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        link = tarfile.TarInfo("root/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../escape"
        bundle.addfile(link, io.BytesIO())
    with pytest.raises(release.ReleaseError, match="link"):
        release.verify_bundle(archive)


def test_release_rejects_invalid_manifest_schema(tmp_path):
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("root/RELEASE-MANIFEST.json", "[]")
    with pytest.raises(release.ReleaseError, match="schema"):
        release.verify_bundle(archive)


def test_additive_integration_migration_preserves_existing_catalog_across_process(tmp_path):
    catalog = Catalog(tmp_path / "workspace")
    project = str(catalog.create_project("Pre-integration project").id)
    before = catalog.get_project(project)
    with catalog.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='model_revisions'").fetchone()
    service = IntegrationService(catalog)
    model = service.import_model(
        {
            "format": "mediasensei-fitted-v1",
            "name": "Migration model",
            "model": {"kind": "tfidf", "vocabulary": ["forest"], "idf": [1.0]},
            "training": {"snapshot_sha256": "a" * 64, "sources": []},
        }
    )
    service.playground(
        project, "Saved script", 'data = fill_missing(data, columns=["income"], strategy="mean")'
    )
    restarted = IntegrationService(Catalog(catalog.workspace))
    assert restarted.catalog.get_project(project) == before
    assert restarted.model(model["revision"])["artifact"] == model["artifact"]
    code = "from mediasensei.infrastructure.catalog import Catalog; from mediasensei.integrations import IntegrationService; import sys,json; s=IntegrationService(Catalog(sys.argv[1])); print(json.dumps({'model':s.models()[0]['revision'],'scripts':len(s.scripts(sys.argv[2])),'policy':s.catalog.get_project(sys.argv[2])['data_policy']}))"
    result = subprocess.run(
        [sys.executable, "-c", code, str(catalog.workspace), project],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    assert json.loads(result.stdout) == {
        "model": model["revision"],
        "scripts": 1,
        "policy": "local_only",
    }
