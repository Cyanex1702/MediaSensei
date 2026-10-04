"""Batch 2 endpoints: bounded previews, output downloads and acquisition review."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .lab import LabRoute, Step

router = APIRouter(prefix="/api/v1/lab", tags=["Multimodal labs"], route_class=LabRoute)


def service():
    from mediasensei.multimodal import BatchService

    from .main import catalog

    return BatchService(catalog)


@router.post("/assets/{asset_id}/preview")
def preview(asset_id: str, body: Step):
    from mediasensei.infrastructure.media import FFmpegUnavailableError

    try:
        return service().preview(asset_id, body.operation, body.parameters)
    except FFmpegUnavailableError as error:
        raise HTTPException(503, detail=str(error)) from error


@router.get("/assets/{asset_id}/image-details")
def image_details(asset_id: str):
    try:
        return service().image_details(asset_id)
    except OSError as error:
        raise ValueError(f"Cannot decode image: {error}") from error


@router.get("/projects/{project_id}/image-distributions")
def distributions(project_id: str):
    return service().distributions(project_id)


@router.get("/projects/{project_id}/asset-outputs")
def outputs(project_id: str):
    return {"items": service().outputs(project_id)}


@router.get("/asset-outputs/{output_id}/artifacts/{index}")
def artifact(output_id: str, index: int):
    s = service()
    result = s.output(output_id)
    if index < 0 or index >= len(result["artifacts"]):
        raise KeyError("Artifact not found")
    a = result["artifacts"][index]
    return FileResponse(
        s.store.resolve(a["object_key"]),
        media_type=a["mime"],
        filename=a["name"],
        content_disposition_type="inline"
        if a["mime"].startswith(("image/", "video/", "audio/"))
        else "attachment",
    )


@router.get("/asset-outputs/{output_id}/download")
def output_bundle(output_id: str):
    import hashlib
    import zipfile

    s = service()
    result = s.output(output_id)
    fd, name = tempfile.mkstemp(suffix=".zip", dir=s.store.temp_root)
    os.close(fd)
    path = Path(name)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            checksums = {}
            manifest = json.dumps(result, indent=2).encode()
            archive.writestr("manifest.json", manifest)
            checksums["manifest.json"] = hashlib.sha256(manifest).hexdigest()
            for a in result["artifacts"]:
                with (
                    s.store.resolve(a["object_key"]).open("rb") as source,
                    archive.open(a["name"], "w") as target,
                ):
                    import shutil

                    shutil.copyfileobj(source, target)
                checksums[a["name"]] = a["sha256"]
            archive.writestr(
                "checksums.sha256", "\n".join(f"{v}  {k}" for k, v in checksums.items())
            )
        return FileResponse(
            path,
            filename=f"mediasensei-{output_id}.zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise


@router.get("/documents/{asset_id}/chunks")
def chunks(asset_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    s = service()
    asset = s.asset(asset_id)
    with s.catalog.connect() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM content_units WHERE asset_id=? AND kind='document_chunk'",
            (asset_id,),
        ).fetchone()[0]
        rows = db.execute(
            """SELECT id, text_content, locator_json FROM content_units WHERE asset_id=? AND kind='document_chunk'
            ORDER BY json_extract(locator_json, '$.sequence') LIMIT ? OFFSET ?""",
            (asset_id, limit, offset),
        ).fetchall()
    return {
        "filename": asset["original_filename"],
        "total": total,
        "offset": offset,
        "index": s.catalog.document_index(asset_id),
        "items": [
            {"id": r["id"], "text": r["text_content"], "locator": json.loads(r["locator_json"])}
            for r in rows
        ],
    }


@router.get("/projects/{project_id}/rag-bundle")
def rag_bundle(project_id: str):
    s = service()
    fd, name = tempfile.mkstemp(suffix=".zip", dir=s.store.temp_root)
    os.close(fd)
    path = Path(name)
    try:
        s.rag_bundle(project_id, path)
        return FileResponse(
            path,
            filename=f"rag-{project_id}.zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise


class PolicyRequest(BaseModel):
    allow_remote: bool = False


@router.post("/projects/{project_id}/acquisition-consent")
def consent(project_id: str, body: PolicyRequest):
    from .main import catalog

    catalog.get_project(project_id)
    policy = "approved_external" if body.allow_remote else "local_only"
    with catalog.connect() as db:
        db.execute("UPDATE projects SET data_policy=? WHERE id=?", (policy, project_id))
    return {"data_policy": policy}


@router.get("/projects/{project_id}/acquisition-runs")
def acquisition_runs(project_id: str):
    from .main import acquisition, catalog

    catalog.get_project(project_id)
    with catalog.connect() as db:
        rows = db.execute(
            "SELECT id FROM acquisition_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 30",
            (project_id,),
        ).fetchall()
    return {"items": [acquisition.repository.run(row[0]) for row in rows]}


@router.get("/acquisition/runs/{run_id}/review")
def acquisition_review(
    run_id: str, state: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    from .main import acquisition, catalog

    run = acquisition.repository.run(run_id)
    with catalog.connect() as db:
        predicates, values = "run_id=?", [run_id]
        if state:
            predicates += " AND state=?"
            values.append(state)
        total = db.execute(
            f"SELECT COUNT(*) FROM acquisition_candidates WHERE {predicates}", values
        ).fetchone()[0]
        rows = db.execute(
            f"SELECT id FROM acquisition_candidates WHERE {predicates} ORDER BY created_at,id LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
        items = []
        for row in rows:
            c = acquisition.repository.candidate(row[0])
            c["decisions"] = [
                {**dict(r), "scores": json.loads(r["scores_json"])}
                for r in db.execute(
                    "SELECT decision,reason,scores_json,evaluator_id FROM acquisition_decisions WHERE candidate_id=? ORDER BY created_at",
                    (row[0],),
                )
            ]
            q = db.execute(
                "SELECT query FROM acquisition_queries WHERE id=?", (c["query_id"],)
            ).fetchone()
            c["query"] = q[0] if q else ""
            items.append(c)
        queries = [
            dict(r)
            for r in db.execute(
                "SELECT provider_id,query,result_count,evaluated_count,accepted_count,exhausted FROM acquisition_queries WHERE run_id=? ORDER BY priority DESC,id",
                (run_id,),
            )
        ]
    return {
        "run": run,
        "items": items,
        "total": total,
        "offset": offset,
        "queries": queries,
        "rejections": acquisition.repository.rejection_summary(run_id),
    }


@router.post("/asset-outputs/{output_id}/artifacts/{index}/adopt", status_code=201)
def adopt_artifact(output_id: str, index: int):
    from mediasensei.asset_operations import enqueue_assets

    from .lab import wb

    s = service()
    output = s.output(output_id)
    if index < 0 or index >= len(output["artifacts"]):
        raise KeyError("Artifact not found")
    a = output["artifacts"][index]
    modality = a["mime"].split("/")[0]
    if modality not in ("image", "video", "audio"):
        modality = "document" if a["mime"] == "text/plain" else ""
    if not modality:
        raise ValueError("This artifact is a report; download it instead.")
    source = s.asset(output["asset_id"])
    with s.catalog.connect() as db:
        old = db.execute(
            "SELECT id FROM assets WHERE project_id=? AND json_extract(metadata_json,'$.output_id')=? AND json_extract(metadata_json,'$.artifact_index')=?",
            (source["project_id"], output_id, index),
        ).fetchone()
    if old:
        return s.asset(old[0])
    identifier = s.catalog.record_asset(
        project_id=source["project_id"],
        source_id=source.get("source_id"),
        sha256=a["sha256"],
        object_key=a["object_key"],
        byte_size=a["bytes"],
        media_type=modality,
        original_filename=f"{Path(source['original_filename']).stem}-{a['name']}",
        metadata={
            **source.get("metadata", {}),
            "parent_asset_id": source["id"],
            "source_sha256": source["sha256"],
            "output_id": output_id,
            "artifact_index": index,
            "operation": output["operation"],
            "parameters": output["parameters"],
        },
    )
    operation = (
        "image.inspect"
        if modality == "image"
        else "document.index"
        if modality == "document"
        else "media.inspect"
    )
    enqueue_assets(wb(), source["project_id"], operation, [identifier], {})
    return s.asset(identifier)
