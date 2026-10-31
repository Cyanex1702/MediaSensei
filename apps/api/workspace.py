"""Workspace inventories and persistent Library collections."""

import shutil
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .lab import LabRoute, wb

router = APIRouter(prefix="/api/v1/workspace", route_class=LabRoute)


class Collection(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    query: str = Field(default="", max_length=1000)
    modality: Literal["all", "image", "video", "audio", "document", "tabular"] = "all"


def setup(service):
    with service.catalog.connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS saved_collections(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,name TEXT NOT NULL,query TEXT NOT NULL,modality TEXT NOT NULL)"
        )


@router.get("/projects/{project_id}/collections")
def collections(project_id: str):
    service = wb()
    service.catalog.get_project(project_id)
    setup(service)
    with service.catalog.connect() as db:
        return {
            "items": [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM saved_collections WHERE project_id=? ORDER BY name,id",
                    (project_id,),
                )
            ]
        }


@router.post("/projects/{project_id}/collections", status_code=201)
def save_collection(project_id: str, payload: Collection):
    service = wb()
    service.catalog.get_project(project_id)
    setup(service)
    identifier = str(uuid4())
    with service.catalog.connect() as db:
        db.execute(
            "INSERT INTO saved_collections VALUES (?,?,?,?,?)",
            (identifier, project_id, payload.name, payload.query, payload.modality),
        )
    return {"id": identifier, **payload.model_dump()}


@router.delete("/projects/{project_id}/collections/{identifier}")
def delete_collection(project_id: str, identifier: str):
    service = wb()
    service.catalog.get_project(project_id)
    setup(service)
    with service.catalog.connect() as db:
        db.execute(
            "DELETE FROM saved_collections WHERE project_id=? AND id=?", (project_id, identifier)
        )
    return {"deleted": True}


@router.get("/storage")
def storage_inventory():
    service = wb()
    root = service.catalog.workspace
    count = total = 0
    for path in (root / "objects").rglob("*"):
        if path.is_file() and not path.is_symlink():
            count += 1
            total += path.stat().st_size
    usage = shutil.disk_usage(root)
    return {
        "stored_objects": count,
        "object_bytes": total,
        "disk_free_bytes": usage.free,
        "backup_instructions": "Stop the app and use Backup-MediaSensei.bat. Restore to a new directory with scripts/workspace_backup.py. Objects may be shared across versions; deleting files manually can break them.",
    }


@router.get("/projects/{project_id}/manifest")
def project_manifest(project_id: str):
    service = wb()
    project = service.catalog.get_project(project_id)
    datasets = service.datasets(project_id)
    return {
        "schema": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": project,
        "assets": service.catalog.list_assets(project_id, state=None),
        "datasets": [{**ds, "versions": service.versions(ds["id"])} for ds in datasets],
        "scope": "Catalog and table-version inventory. Download replay bundles from Exports for dataset bytes and executable workflows. OS credentials are not exported.",
    }
