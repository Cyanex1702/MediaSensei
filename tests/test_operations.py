from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest
from mediasensei.operations import Workbench, execute_frame
from test_real_app_flow import _client, _drain_worker

import apps.api.main as api_module


@pytest.fixture
def lab_client(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "2.0 data"}).json()["id"]
    raw = b"age,income,label\n20,10,a\n30,,b\n40,30,a\n20,10,a\n"
    response = client.post(
        f"/api/v1/projects/{project}/assets", files={"file": ("data.csv", raw, "text/csv")}
    )
    assert response.status_code == 202, response.text
    _drain_worker()
    source = client.get(f"/api/v1/projects/{project}/tabular").json()["items"][0]
    ds = client.post("/api/v1/lab/datasets/from-table/" + source["id"]).json()
    return client, ds, raw


def test_preview_execution_version_restore_and_reproducibility(lab_client):
    client, ds, _raw = lab_client
    path = "/api/v1/lab/datasets/" + ds["id"]
    root = ds["head_key"]
    step = {"operation": "fill_missing", "parameters": {"columns": ["income"], "strategy": "mean"}}
    preview = client.post(path + "/preview", json=step)
    assert preview.status_code == 200, preview.text
    assert preview.json()["after"][1]["income"] == pytest.approx(50 / 3)
    assert client.get(path).json()["dataset"]["head_key"] == root
    version = client.post(path + "/versions", json={"name": "Original"}).json()
    result = client.post(path + "/runs", json={"steps": [step], "revision": 0})
    assert result.status_code == 202, result.text
    _drain_worker()
    runs = client.get(path + "/runs").json()["items"]
    assert runs[0]["state"] == "completed", runs
    assert client.get(path).json()["dataset"]["revision"] == 1
    bundle = client.get(path + "/export?bundle=true")
    assert bundle.status_code == 200, bundle.text
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert {
            "input.parquet",
            "dataset.parquet",
            "workflow.py",
            "manifest.json",
            "dataset-card.md",
            "SHA256SUMS",
        } <= set(archive.namelist())
        assert len(pd.read_parquet(io.BytesIO(archive.read("dataset.parquet")))) == 4
    restore = client.post(path + "/versions/" + version["id"] + "/restore", json={"revision": 1})
    assert restore.status_code == 200, restore.text
    assert restore.json()["head_key"] == root
    assert restore.json()["lineage_json"] == "[]"
    assert Workbench(api_module.WORKSPACE).dataset(ds["id"])["revision"] == 2
    assert client.get(path + "/versions").json()["items"][0]["manifest"]["head_key"] == root


def test_stale_concurrent_runs_never_overwrite(lab_client):
    client, ds, _ = lab_client
    path = "/api/v1/lab/datasets/" + ds["id"]
    body = {"steps": [{"operation": "drop_duplicates", "parameters": {}}], "revision": 0}
    assert client.post(path + "/runs", json=body).status_code == 202
    assert client.post(path + "/runs", json=body).status_code == 202
    _drain_worker()
    runs = client.get(path + "/runs").json()["items"]
    assert sorted(r["state"] for r in runs) == ["completed", "failed"]
    assert client.get(path).json()["profile"]["rows"] == 3
    assert client.get(path).json()["dataset"]["revision"] == 1


def test_registry_alias_validation_and_pagination(lab_client):
    client, ds, _ = lab_client
    path = "/api/v1/lab/datasets/" + ds["id"]
    matches = client.get("/api/v1/lab/operations?q=make%20heat%20map").json()["items"]
    assert "correlation" in [m["id"] for m in matches]
    assert client.get(path + "/rows?limit=2&offset=2").json()["total"] == 4
    assert len(client.get(path + "/rows?limit=2&offset=2").json()["rows"]) == 2
    assert client.get(path + "/rows?limit=10000").status_code == 422
    assert (
        client.post(
            path + "/preview", json={"operation": "scale", "parameters": {"columns": ["label"]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path + "/preview",
            json={"operation": "profile", "parameters": {"code": '__import__("os")'}},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "operation,params",
    [
        ("profile", {}),
        ("missing", {}),
        ("correlation", {}),
        ("distribution", {"column": "label"}),
        ("fill_missing", {"columns": ["income"], "strategy": "median"}),
        ("drop_missing", {}),
        ("drop_duplicates", {}),
        ("drop_columns", {"columns": ["label"]}),
        ("scale", {"columns": ["age"], "method": "standard"}),
        ("encode", {"columns": ["label"]}),
        ("filter", {"column": "age", "operator": "greater", "value": "20"}),
        ("sort", {"column": "age"}),
        ("rename", {"column": "age", "name": "years"}),
        ("cast", {"column": "age", "dtype": "string"}),
        ("clip", {"columns": ["age"]}),
        ("split", {"strategy": "stratified", "column": "label"}),
    ],
)
def test_operation_purity_and_determinism(operation, params):
    frame = pd.DataFrame(
        {"age": [20, 30, 40, 20], "income": [10.0, None, 30.0, 10.0], "label": ["a", "b", "a", "a"]}
    )
    original = frame.copy(deep=True)
    first, _, _ = execute_frame(frame, operation, params)
    second, _, _ = execute_frame(frame, operation, params)
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(first, second)


def test_group_split_keeps_groups_together():
    frame = pd.DataFrame(
        {"group": ["a"] * 10 + ["b"] * 10 + ["c"] * 10 + ["d"] * 10, "value": range(40)}
    )
    result, _, _ = execute_frame(frame, "split", {"strategy": "group", "column": "group"})
    assert result.groupby("group")["_split"].nunique().max() == 1


def test_cache_skips_transform_and_recipe_replays(lab_client, monkeypatch, tmp_path):
    import json
    import subprocess
    import sys

    import mediasensei.operations as operation_module

    client, ds, _raw = lab_client
    path = "/api/v1/lab/datasets/" + ds["id"]
    original = client.post(path + "/versions", json={"name": "Before"}).json()
    step = {"operation": "fill_missing", "parameters": {"columns": ["income"], "strategy": "mean"}}
    client.post(path + "/runs", json={"steps": [step], "revision": 0})
    _drain_worker()
    bundle = client.get(path + "/export?bundle=true")
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        for name in ("input.parquet", "dataset.parquet", "workflow.py"):
            (tmp_path / name).write_bytes(archive.read(name))
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["runs"]) == 1
    subprocess.run([sys.executable, str(tmp_path / "workflow.py")], cwd=tmp_path, check=True)
    pd.testing.assert_frame_equal(
        pd.read_parquet(tmp_path / "output.parquet"), pd.read_parquet(tmp_path / "dataset.parquet")
    )
    client.post(path + "/versions/" + original["id"] + "/restore", json={"revision": 1})
    monkeypatch.setattr(
        operation_module,
        "execute_frame",
        lambda *args: pytest.fail("Cache hit should skip transformation"),
    )
    client.post(path + "/runs", json={"steps": [step], "revision": 2})
    _drain_worker()
    latest = client.get(path + "/runs").json()["items"][0]
    assert latest["state"] == "completed", latest
    assert latest["data"]["cache_hit"] is True


def test_acquisition_plan_is_discoverable_without_download(lab_client, monkeypatch):
    from mediasensei.infrastructure.acquisition import AcquisitionService

    monkeypatch.setattr(api_module, "acquisition", AcquisitionService(api_module.catalog))
    client, ds, _raw = lab_client
    response = client.post(
        "/api/v1/projects/" + ds["project_id"] + "/acquisition/requests",
        json={"prompt": "Find 200 red fox photos, minimum 1024 pixels."},
    )
    assert response.status_code == 201, response.text
    assert response.json()["plan"]["spec"]["target"]["count"] == 200

@pytest.mark.parametrize('prompt',[
 'Find 200 red fox photos, minimum 1024 pixels.',
 'I want 200 photographs of red foxes in snowy forests, at least 1024px, avoid illustrations.',
 'Get 200 images of red foxes, minimum 1024 pixels.',
])
def test_natural_acquisition_counts_and_constraints(prompt):
    from mediasensei.infrastructure.acquisition_planning import RuleBasedPromptPlanner
    plan=RuleBasedPromptPlanner().plan(prompt)
    assert plan.target.count==200
    assert plan.min_width==1024
    assert 'minimum' not in plan.topic
