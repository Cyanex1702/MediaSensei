from __future__ import annotations

import json
import os
import zipfile

import pytest
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.integrations import IntegrationService
from mediasensei.learned import fit_model
from mediasensei.multimodal import BatchService
from mediasensei.operations import Workbench
from mediasensei.playground import compile_script
from test_real_app_flow import _client, _drain_worker

import apps.api.main as api_module


def documents(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "Batch 3"}).json()["id"]
    ids = []
    for name, text in [
        ("english.md", "The red fox lives in a forest. The fox hunts mice and eats food."),
        (
            "french.md",
            "Le renard rouge habite dans la foret. Le renard mange des souris et de la nourriture.",
        ),
    ]:
        r = client.post(
            f"/api/v1/projects/{project}/assets",
            files={"file": (name, text.encode(), "text/markdown")},
        )
        assert r.status_code == 202, r.text
        ids.append(r.json()["asset"]["id"])
    _drain_worker()
    return client, project, ids, IntegrationService(api_module.catalog)


def test_model_training_indexing_search_export_and_restart(tmp_path):
    client, project, ids, service = documents(tmp_path)
    path = f"/api/v1/integrations/projects/{project}/models/train"
    body = {"name": "Forest retrieval", "asset_ids": ids}
    assert client.post(path, json=body).status_code == 422
    response = client.post(path, json={**body, "confirmed": True})
    assert response.status_code == 202, response.text
    _drain_worker()
    model = service.models()[0]
    revision = model["revision"]
    assert service.model(revision)["artifact"]["training"]["sources"][0]["asset_id"] == ids[0]
    response = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "document.embed",
            "asset_ids": ids,
            "parameters": {"model_revision": revision},
        },
    )
    assert response.status_code == 202, response.text
    _drain_worker()
    restarted = IntegrationService(Catalog(api_module.WORKSPACE))
    hits = restarted.search(project, revision, "fox forest mice")
    assert hits and hits[0]["asset_id"] == ids[0]
    bundle = tmp_path / "rag.zip"
    BatchService(restarted.catalog).rag_bundle(project, bundle)
    with zipfile.ZipFile(bundle) as archive:
        artifact = json.loads(archive.read(f"models/{revision}.json"))
        assert artifact["model"]["kind"] == "tfidf"
        assert (
            json.loads(archive.read("retrieval-config.json"))["providers"][0]["revision"]
            == revision
        )
    assert restarted.import_model(artifact)["revision"] == revision
    assert len(restarted.models()) == 1


def test_model_archive_blocks_already_queued_indexing_and_tamper_is_detected(tmp_path):
    client, project, ids, service = documents(tmp_path)
    service.train(project, "Archive me", "tfidf", ids, {})
    _drain_worker()
    model = service.models()[0]
    r = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "document.embed",
            "asset_ids": ids,
            "parameters": {"model_revision": model["revision"]},
        },
    )
    assert r.status_code == 202
    service.archive_model(model["revision"], True)
    _drain_worker()
    assert api_module.queue.get(r.json()["job_id"]).state.value in {
        "failed",
        "completed_with_errors",
    }
    service.store.resolve(model["object_key"]).write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        service.model(model["revision"])


def test_supervised_language_classifier_and_unknown_words(tmp_path):
    _, project, ids, service = documents(tmp_path)
    service.train(project, "Language", "language", ids, {ids[0]: "en", ids[1]: "fr"})
    _drain_worker()
    revision = service.models()[0]["revision"]
    assert service.language(revision, "the fox lives in the forest")["language"] == "en"
    assert service.language(revision, "le renard rouge dans la foret")["language"] == "fr"
    assert service.language(revision, "xyzzy foobar")["language"] == "und"


def test_training_limits_and_project_isolation(tmp_path):
    _, _, ids, service = documents(tmp_path)
    other = str(service.catalog.create_project("Other").id)
    with pytest.raises(ValueError, match="unavailable"):
        service.train(other, "No cross-project data", "tfidf", ids, {})
    with pytest.raises(ValueError, match="1000"):
        fit_model(["word"] * 1001, "tfidf", [])


@pytest.mark.parametrize(
    "source",
    [
        "import os",
        "data = __import__('os')",
        "data = data.__class__",
        "while True: pass",
        "data = fill_missing(data, columns=[x for x in data])",
        "data = fill_missing(data, **{})",
        "data = fill_missing(data, columns=open('secret'))",
    ],
)
def test_playground_rejects_arbitrary_code(source):
    with pytest.raises(ValueError):
        compile_script(source)


def test_playground_runs_real_workflow_and_preserves_source(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "Playground"}).json()["id"]
    r = client.post(
        f"/api/v1/projects/{project}/assets",
        files={"file": ("data.csv", b"income,label\n10,a\n,b\n30,c\n", "text/csv")},
    )
    assert r.status_code == 202
    _drain_worker()
    imported = client.get(f"/api/v1/projects/{project}/tabular").json()["items"][0]
    wb = Workbench(api_module.catalog)
    dataset = wb.adopt(imported["id"])
    source = 'data = fill_missing(data, columns=["income"], strategy="mean")'
    service = IntegrationService(api_module.catalog)
    result = service.playground(
        project, "Fill income", source, dataset=dataset["id"], revision=0, execute=True
    )
    _drain_worker()
    assert wb.run_record(result["run"]["run_id"])["state"] == "completed"
    frame = wb.frame(wb.dataset(dataset["id"])["head_key"])
    assert frame["income"].tolist() == [10, 20, 30]
    assert service.scripts(project)[0]["source"] == source


class FakeVault:
    def __init__(self):
        self.secrets = {}

    def put(self, identifier, secret):
        self.secrets[identifier] = secret

    def get(self, identifier):
        return self.secrets[identifier]

    def delete(self, identifier):
        self.secrets.pop(identifier, None)


def test_connections_never_persist_secrets_and_revocation_blocks_queued_import(
    tmp_path, monkeypatch
):
    import mediasensei.integrations as module

    vault = FakeVault()
    monkeypatch.setattr(module, "CredentialVault", lambda workspace: vault)
    client, project, _, service = documents(tmp_path)
    secret = "credential-canary-do-not-persist"
    response = client.post(
        "/api/v1/integrations/connections",
        json={"name": "Private", "provider": "huggingface", "secret": secret},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert secret not in response.text
    with pytest.raises(ValueError, match="consent"):
        service.queue_import(project, identifier, "owner/dataset", None, True)
    client.post(f"/api/v1/lab/projects/{project}/acquisition-consent", json={"allow_remote": True})
    job = service.queue_import(project, identifier, "owner/dataset", None, True)
    service.revoke_connection(identifier)
    _drain_worker()
    assert api_module.queue.get(job["job_id"]).state.value in {
        "failed",
        "completed_with_errors",
    }
    with service.catalog.connect() as db:
        dump = "\n".join(db.iterdump())
    assert secret not in dump
    assert not vault.secrets


def test_provider_errors_redact_vault_secret_before_catalog_and_worker_log(tmp_path, monkeypatch):
    import mediasensei.integrations as module
    from mediasensei.infrastructure.providers import HuggingFaceDatasetProvider

    vault = FakeVault()
    monkeypatch.setattr(module, "CredentialVault", lambda workspace: vault)
    client, project, _, service = documents(tmp_path)
    secret = "provider-failure-canary-secret"
    connection = service.save_connection("Test", "huggingface", secret)
    client.post(f"/api/v1/lab/projects/{project}/acquisition-consent", json={"allow_remote": True})
    monkeypatch.setattr(HuggingFaceDatasetProvider, "available", lambda self: True)

    def failed(*args, **kwargs):
        raise RuntimeError("provider echoed " + secret)

    monkeypatch.setattr(HuggingFaceDatasetProvider, "resolve", failed)
    service.queue_import(project, connection["id"], "owner/dataset", None, True)
    _drain_worker()
    with service.catalog.connect() as db:
        dump = "\n".join(db.iterdump())
    assert secret not in dump
    assert "[redacted]" in dump


@pytest.mark.skipif(os.name != "nt", reason="Windows native speech provider")
def test_local_voice_personality_worker_and_audio_output(tmp_path):
    from mediasensei.native_adapters import installed_voices

    voices = installed_voices()
    if not voices:
        pytest.skip("No installed Windows speech voice")
    client, project, ids, service = documents(tmp_path)
    voice = service.save_voice("Narrator", voices[0], 1)
    response = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "document.speak",
            "asset_ids": [ids[0]],
            "parameters": {"personality": voice["id"]},
        },
    )
    assert response.status_code == 202, response.text
    _drain_worker()
    output = BatchService(service.catalog).outputs(project)[0]
    assert output["operation"] == "document.speak"
    assert output["artifacts"][0]["mime"] == "audio/wav"
    assert (
        service.store.resolve(output["artifacts"][0]["object_key"]).read_bytes().startswith(b"RIFF")
    )
    assert IntegrationService(Catalog(api_module.WORKSPACE)).voices()[0]["id"] == voice["id"]


def test_asr_missing_configuration_is_explicit(tmp_path, monkeypatch):
    from mediasensei.native_adapters import asr_available, transcribe

    monkeypatch.delenv("MEDIASENSEI_WHISPER_CPP", raising=False)
    monkeypatch.delenv("MEDIASENSEI_WHISPER_MODEL", raising=False)
    assert not asr_available()
    with pytest.raises(ValueError, match="Configure local"):
        transcribe(None, tmp_path / "audio.wav", {}, tmp_path)


def test_asr_refuses_changed_model_before_execution(tmp_path, monkeypatch):
    from mediasensei.native_adapters import asr_revisions, transcribe

    executable, model = tmp_path / "tool.exe", tmp_path / "model.bin"
    executable.write_bytes(b"not executed")
    model.write_bytes(b"original model")
    monkeypatch.setenv("MEDIASENSEI_WHISPER_CPP", str(executable))
    monkeypatch.setenv("MEDIASENSEI_WHISPER_MODEL", str(model))
    pinned = asr_revisions()
    model.write_bytes(b"changed model")
    with pytest.raises(ValueError, match="changed since"):
        transcribe(None, tmp_path / "audio.wav", pinned, tmp_path)


def test_malformed_model_classes_are_rejected():
    from mediasensei.learned import validate_model

    with pytest.raises(ValueError, match="classes"):
        validate_model({"kind": "language", "vocabulary": ["word"], "classes": [[], []]})


@pytest.mark.skipif(os.name != "nt", reason="Native speech fixture requires Windows")
def test_native_transcription_through_worker_with_pinned_provenance(tmp_path):
    from mediasensei.native_adapters import asr_available, installed_voices

    if not asr_available():
        pytest.skip("Explicit local whisper.cpp executable and model not configured")
    client, project, ids, service = documents(tmp_path)
    voice = service.save_voice("ASR fixture", installed_voices()[0], 0)
    response = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "document.speak",
            "asset_ids": [ids[0]],
            "parameters": {"personality": voice["id"]},
        },
    )
    assert response.status_code == 202
    _drain_worker()
    audio = BatchService(service.catalog).outputs(project)[0]["artifacts"][0]
    response = client.post(
        f"/api/v1/projects/{project}/assets",
        files={
            "file": (
                "speech.wav",
                service.store.resolve(audio["object_key"]).read_bytes(),
                "audio/wav",
            )
        },
    )
    assert response.status_code == 202
    asset = response.json()["asset"]["id"]
    _drain_worker()
    response = client.post(
        f"/api/v1/lab/projects/{project}/asset-operations",
        json={
            "operation": "audio.transcribe",
            "asset_ids": [asset],
            "parameters": {"language": "en", "duration": 20},
        },
    )
    assert response.status_code == 202, response.text
    _drain_worker()
    assert api_module.queue.get(response.json()["job_id"]).state.value == "completed"
    output = next(
        item
        for item in BatchService(service.catalog).outputs(project)
        if item["operation"] == "audio.transcribe"
    )
    text = service.store.resolve(output["artifacts"][0]["object_key"]).read_text().lower()
    assert "fox" in text and "forest" in text
