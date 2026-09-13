"""Thin adapters for explicitly invoked Batch 3 workflows."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .lab import LabRoute

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"], route_class=LabRoute)


def service():
    from mediasensei.integrations import IntegrationService

    from .main import catalog

    return IntegrationService(catalog)


class Training(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "tfidf"
    asset_ids: list[str] = Field(min_length=1, max_length=100)
    labels: dict[str, str] = Field(default_factory=dict)
    confirmed: bool = False


class Query(BaseModel):
    revision: str = Field(min_length=64, max_length=64)
    text: str = Field(min_length=1, max_length=200000)


class Script(BaseModel):
    name: str = Field(default="Untitled script", max_length=120)
    source: str = Field(min_length=1, max_length=16384)
    dataset: str | None = None
    revision: int | None = None
    execute: bool = False


class ImportRequest(BaseModel):
    connection: str
    dataset: str = Field(max_length=200)
    revision: str | None = Field(default=None, max_length=200)
    allow_remote: bool = False


class Voice(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    voice: str = Field(max_length=200)
    rate: int = Field(default=0, ge=-10, le=10)


@router.get("/projects/{project_id}")
def inventory(project_id: str):
    from mediasensei.native_adapters import asr_available, installed_voices

    s = service()
    s.catalog.get_project(project_id)
    try:
        voices = installed_voices()
    except ValueError:
        voices = []
    return {
        "models": s.models(),
        "connections": s.connections(),
        "scripts": s.scripts(project_id),
        "personalities": s.voices(),
        "installed_voices": voices,
        "asr_available": asr_available(),
    }


@router.post("/projects/{project_id}/models/train", status_code=202)
def train(project_id: str, body: Training):
    if not body.confirmed:
        raise ValueError("Confirm local training before queueing it.")
    return service().train(project_id, body.name, body.kind, body.asset_ids, body.labels)


@router.post("/models/import", status_code=201)
def import_model(body: dict):
    return service().import_model(body)


@router.get("/models/{revision}")
def model(revision: str):
    return service().model(revision)


@router.get("/models/{revision}/download")
def download_model(revision: str):
    s = service()
    model = s.model(revision)
    return FileResponse(
        s.store.resolve(model["object_key"]),
        media_type="application/json",
        filename=f"model-{revision}.json",
    )


@router.post("/models/{revision}/archive")
def archive_model(revision: str, body: dict):
    if type(body.get("archived")) is not bool:
        raise ValueError("Set archived to true or false.")
    return service().archive_model(revision, body["archived"])


@router.post("/projects/{project_id}/search")
def search(project_id: str, body: Query):
    return {"items": service().search(project_id, body.revision, body.text)}


@router.post("/language")
def language(body: Query):
    return service().language(body.revision, body.text)


@router.post("/connections", status_code=201)
def connection(body: dict):
    # Avoid echoing a rejected secret through Pydantic validation errors.
    return service().save_connection(body.get("name"), body.get("provider"), body.get("secret"))


@router.post("/connections/{identifier}/revoke")
def revoke(identifier: str):
    return service().revoke_connection(identifier)


@router.post("/projects/{project_id}/imports", status_code=202)
def import_dataset(project_id: str, body: ImportRequest):
    return service().queue_import(
        project_id, body.connection, body.dataset, body.revision, body.allow_remote
    )


@router.post("/projects/{project_id}/playground")
def playground(project_id: str, body: Script):
    return service().playground(
        project_id,
        body.name,
        body.source,
        dataset=body.dataset,
        revision=body.revision,
        execute=body.execute,
    )


@router.post("/voices", status_code=201)
def save_voice(body: Voice):
    return service().save_voice(body.name, body.voice, body.rate)
