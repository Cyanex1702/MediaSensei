"""Thin REST adapter for the shared local operation SDK."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from mediasensei.domain.operations import REGISTRY
from mediasensei.domain.tabular import TabularQuery
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask


class LabRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def route(request):
            try:
                return await original(request)
            except KeyError as error:
                raise HTTPException(
                    404, detail={"code": "NOT_FOUND", "message": str(error).strip("'")}
                ) from error
            except ValueError as error:
                raise HTTPException(
                    422, detail={"code": "INVALID_OPERATION", "message": str(error)}
                ) from error

        return route


router = APIRouter(prefix="/api/v1/lab", tags=["Operation workbench"], route_class=LabRoute)


def wb():
    from mediasensei.operations import Workbench

    from .main import catalog

    return Workbench(catalog)


class Step(BaseModel):
    operation: str = Field(min_length=1, max_length=120)
    parameters: dict = Field(default_factory=dict)


class RunRequest(BaseModel):
    bindings: dict = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1, max_length=30)
    revision: int = Field(ge=0)


class PreviewRequest(Step):
    mode: str = "first"
    seed: int = Field(default=42, ge=0, le=4294967295)
    selected: list[int] = Field(default_factory=list, max_length=500)
    sample: int = Field(default=100, ge=1, le=500)


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RecipeRequest(NameRequest):
    id: str | None = None
    steps: list[Step] = Field(min_length=1, max_length=30)


class RestoreRequest(BaseModel):
    revision: int = Field(ge=0)


@router.get("/operations")
def operations(q: str = "", category: str = "", modality: str = "tabular"):
    return {"items": [operation.to_dict() for operation in REGISTRY.search(q, category, modality)]}


@router.post("/datasets/from-table/{source_id}", status_code=201)
def adopt(source_id: str):
    return wb().adopt(source_id)


@router.get("/projects/{project_id}/datasets")
def datasets(project_id: str):
    return {"items": wb().datasets(project_id)}


@router.get("/datasets/{dataset_id}")
def overview(dataset_id: str):
    return wb().overview(dataset_id)


@router.get("/datasets/{dataset_id}/rows")
def rows(
    dataset_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    search: str = "",
    sort_by: str = "",
    descending: bool = False,
):
    service = wb()
    return service.engine.query(
        service.dataset(dataset_id)["head_key"],
        TabularQuery(
            offset=offset,
            limit=limit,
            search=search,
            sort_by=sort_by or None,
            descending=descending,
        ),
    )


@router.post("/datasets/{dataset_id}/preview")
def preview(dataset_id: str, body: PreviewRequest):
    return wb().preview(
        dataset_id,
        body.operation,
        body.parameters,
        body.sample,
        body.mode,
        body.seed,
        body.selected,
    )


@router.post("/datasets/{dataset_id}/runs", status_code=202)
def enqueue(dataset_id: str, body: RunRequest):
    from mediasensei.workflows import resolve_parameters

    return wb().enqueue(
        dataset_id,
        resolve_parameters([step.model_dump() for step in body.steps], body.bindings),
        body.revision,
    )


@router.get("/datasets/{dataset_id}/runs")
def runs(dataset_id: str):
    return {"items": wb().runs(dataset_id)}


@router.get("/runs/{run_id}")
def run(run_id: str):
    return wb().run_record(run_id)


@router.post("/datasets/{dataset_id}/versions", status_code=201)
def version(dataset_id: str, body: NameRequest):
    return wb().version(dataset_id, body.name)


@router.get("/datasets/{dataset_id}/versions")
def versions(dataset_id: str):
    return {"items": wb().versions(dataset_id)}


@router.post("/datasets/{dataset_id}/versions/{version_id}/restore")
def restore(dataset_id: str, version_id: str, body: RestoreRequest):
    return wb().restore(dataset_id, version_id, body.revision)


@router.get("/recipes")
def recipes():
    return {"items": wb().recipes()}


@router.post("/recipes", status_code=201)
def save_recipe(body: RecipeRequest):
    return wb().save_recipe(body.name, [step.model_dump() for step in body.steps], body.id)


@router.post("/datasets/{dataset_id}/workflow-preview")
def workflow_preview(dataset_id: str, body: RunRequest):
    return wb().dry_run(
        dataset_id, [step.model_dump() for step in body.steps], body.revision, body.bindings
    )


@router.post("/datasets/{dataset_id}/python")
def python_code(dataset_id: str, body: RunRequest):
    from mediasensei.workflows import resolve_parameters

    return {
        "code": wb().python(
            dataset_id,
            resolve_parameters([step.model_dump() for step in body.steps], body.bindings),
        )
    }


@router.get("/datasets/{dataset_id}/export")
def export(dataset_id: str, version_id: str = "", bundle: bool = False):
    service = wb()
    dataset = service.dataset(dataset_id)
    if version_id:
        snapshot = next((v for v in service.versions(dataset_id) if v["id"] == version_id), None)
        if snapshot is None:
            raise KeyError("Version not found.")
        manifest = snapshot["manifest"]
    else:
        manifest = {
            **dataset,
            "runs": [service.run_record(run_id) for run_id in json.loads(dataset["lineage_json"])],
        }
    source = service.store.resolve(manifest["head_key"])
    if not bundle:
        return FileResponse(
            source, filename="dataset.parquet", media_type="application/octet-stream"
        )
    import hashlib
    import shutil

    folder = Path(tempfile.mkdtemp(prefix="repro-export-", dir=service.store.temp_root))
    target = folder / "dataset.zip"
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, "dataset.parquet")
            archive.write(service.store.resolve(manifest["root_key"]), "input.parquet")
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            steps = [
                s
                for r in manifest.get("runs", [])
                if r["state"] == "completed"
                for s in r["data"]["steps"]
            ]
            # Rename replay input aliases by their hash when the same dataset was joined at different revisions.
            for run in manifest.get("runs", []):
                for identifier, key in run["data"].get("inputs", {}).items():
                    alias = identifier + "-" + Path(key).name
                    filename = f"inputs/{alias}.parquet"
                    if filename not in archive.namelist():
                        with (
                            service.store.resolve(key).open("rb") as source_file,
                            archive.open(filename, "w") as target_file,
                        ):
                            shutil.copyfileobj(source_file, target_file)
                    for step in run["data"]["steps"]:
                        if (
                            step["operation"] == "combine"
                            and step["parameters"]["dataset"] == identifier
                        ):
                            step["parameters"]["dataset"] = alias
            archive.writestr("workflow.py", service.python(dataset_id, steps))
            archive.writestr(
                "dataset-card.md",
                f"# {dataset['name']}\n\nLocal dataset export. Original source bytes are immutable.\n\nRevision: {manifest['revision']}\n\nSee manifest.json for operation parameters, versions and processing history.\n",
            )
            checksums = []
            for filename in archive.namelist():
                checksums.append(
                    hashlib.sha256(archive.read(filename)).hexdigest() + "  " + filename
                )
            archive.writestr("SHA256SUMS", "\n".join(checksums) + "\n")
    except Exception:
        shutil.rmtree(folder)
        raise
    return FileResponse(
        target,
        filename="dataset-reproducibility.zip",
        media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, folder),
    )


@router.post("/datasets/{dataset_id}/query")
def query_rows(dataset_id: str, body: dict):
    return wb().query_rows(dataset_id, body)


@router.get("/datasets/{dataset_id}/queries")
def query_history(dataset_id: str):
    return {"items": wb().query_history(dataset_id)}


@router.get("/datasets/{dataset_id}/compare")
def compare(dataset_id: str, left: str, right: str = "", identity: str = "", target: str = ""):
    return wb().compare_versions(dataset_id, left, right, identity, target)


@router.get("/projects/{project_id}/workflows")
def workflows(project_id: str):
    return {"items": wb().workflows(project_id)}


@router.post("/projects/{project_id}/workflows")
def save_workflow(project_id: str, body: RecipeRequest):
    return wb().save_workflow(project_id, body.name, [s.model_dump() for s in body.steps], body.id)


@router.get("/datasets/{dataset_id}/charts")
def charts(dataset_id: str):
    return {"items": wb().charts(dataset_id)}


class ChartRequest(NameRequest):
    definition: dict


@router.post("/datasets/{dataset_id}/charts")
def save_chart(dataset_id: str, body: ChartRequest):
    return wb().save_chart(dataset_id, body.name, body.definition)


@router.post("/recipes/{recipe_id}/run")
def run_recipe(recipe_id: str, body: dict):
    from mediasensei.workflows import resolve_parameters

    service = wb()
    recipe = next((r for r in service.recipes() if r["id"] == recipe_id), None)
    if recipe is None:
        raise KeyError("Recipe not found.")
    return service.enqueue(
        body["dataset_id"],
        resolve_parameters(recipe["steps"], body.get("bindings", {})),
        body["revision"],
    )


@router.get("/functions")
def functions(q: str = ""):
    from mediasensei.discovery import search_functions

    return {"items": search_functions(q)}


@router.get("/search")
def search(q: str = "", project_id: str = ""):
    from mediasensei.discovery import search_workspace

    from .main import plugin_runtime
    hits=search_workspace(wb(),q,project_id)
    for plugin in plugin_runtime.snapshot().get("plugins",[]):
        if not q or q.lower() in plugin["name"].lower():
            hits.append({"id":plugin["name"],"kind":"Plugin","name":plugin["name"],"description":"Installed v"+plugin["version"]+"; "+", ".join(plugin["capabilities"]),"view":"System"})
    return {"items":hits}


@router.get("/guides")
def guides():
    from mediasensei.discovery import GUIDES

    return {"items": [{"id": i, "name": n, "description": d} for i, n, d in GUIDES]}


class AssetOperationRequest(BaseModel):
    operation: str
    asset_ids: list[str] = Field(min_length=1, max_length=10000)
    parameters: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/asset-operations", status_code=202)
def asset_operation(project_id: str, body: AssetOperationRequest):
    from mediasensei.asset_operations import enqueue_assets

    return enqueue_assets(wb(), project_id, body.operation, body.asset_ids, body.parameters)
