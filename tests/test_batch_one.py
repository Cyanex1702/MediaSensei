from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from mediasensei.operations import Workbench, execute_frame
from mediasensei.workflows import resolve_parameters
from test_operations import lab_client as lab_client  # noqa: PLC0414
from test_real_app_flow import _drain_worker

import apps.api.main as api_module


@pytest.mark.parametrize(
    "operation,params",
    [
        ("statistics", {"columns": ["x"], "method": "quantiles"}),
        ("duplicates", {"columns": ["category"]}),
        ("exclude", {"rows": [1]}),
        ("conditions", {"conditions": [{"column": "x", "operator": "ge", "value": 2}]}),
        ("derive", {"name": "double", "expression": "x * 2 + 1"}),
        ("strings", {"column": "text", "method": "strip"}),
        ("dates", {"column": "date", "name": "year", "method": "year"}),
        ("replace", {"column": "category", "mapping": {"a": "A"}}),
        ("aggregate", {"by": ["category"], "columns": ["x"], "method": "mean"}),
        ("pivot", {"index": "category", "column": "text", "value": "x", "method": "sum"}),
        ("melt", {"columns": ["category"]}),
        ("explode", {"column": "text", "separator": ","}),
        ("ordinal", {"column": "category", "categories": ["a", "b"], "name": "encoded"}),
        ("log", {"columns": ["x"]}),
        ("outliers", {"columns": ["x"]}),
        ("quality", {"target": "category"}),
        ("chart", {"kind": "scatter", "x": "x", "y": "y"}),
    ],
)
def test_new_operations_are_deterministic_and_immutable(operation, params):
    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 8.0],
            "y": [2.0, 5.0, 6.0, 9.0],
            "category": ["a", "b", "a", "b"],
            "text": [" a ", "b,c", "d", "e"],
            "date": ["2024-01-01"] * 4,
        }
    )
    original = frame.copy(deep=True)
    a, _chart, p = execute_frame(frame, operation, params)
    b, _, _ = execute_frame(frame, operation, params)
    pd.testing.assert_frame_equal(frame, original)
    pd.testing.assert_frame_equal(a, b)
    assert p is not None


@pytest.mark.parametrize(
    "kind",
    [
        "histogram",
        "density",
        "box",
        "violin",
        "bar",
        "grouped",
        "stacked",
        "scatter",
        "bubble",
        "pair",
        "missingness",
        "line",
        "rolling",
        "qq",
        "error",
        "outlier",
        "split",
    ],
)
def test_chart_family_returns_finite_serializable_data(kind):
    frame = pd.DataFrame(
        {
            "x": np.arange(40, dtype=float),
            "y": np.arange(40, dtype=float) ** 2,
            "g": [1, 2] * 20,
            "_split": ["train"] * 30 + ["test"] * 10,
        }
    )
    _, chart, _ = execute_frame(frame, "chart", {"kind": kind, "x": "x", "y": "y", "group": "g"})
    json.dumps(chart, allow_nan=False)
    assert chart["values"]


def test_fitting_uses_training_rows_and_unknown_categories():
    frame = pd.DataFrame(
        {
            "n": [1.0, 3.0, 1000.0, None],
            "cat": ["a", "b", "unseen", None],
            "target": [0, 1, 1, 0],
            "_split": ["train", "train", "test", "validation"],
        }
    )
    out, report, _ = execute_frame(
        frame, "preprocess", {"numeric": ["n"], "categorical": ["cat"], "target": "target"}
    )
    assert out.n.tolist() == [-1.0, 1.0, 998.0, 0.0]
    assert report["fitted"]["cat"]["categories"] == ["a", "b"]
    assert out.loc[2, ["cat__0", "cat__1"]].sum() == 0
    assert out.cat__missing.tolist() == [0, 0, 0, 1]
    with pytest.raises(ValueError):
        execute_frame(frame, "preprocess", {"numeric": ["target"], "target": "target"})


@pytest.mark.parametrize(
    "text", ["__import__('os').system('x')", "x.__class__", "x[0]", "10 ** 99999999"]
)
def test_expression_language_cannot_execute_python(text):
    with pytest.raises(ValueError):
        execute_frame(pd.DataFrame({"x": [1]}), "derive", {"name": "danger", "expression": text})


def test_compound_conditions_and_join_cardinality():
    frame = pd.DataFrame({"id": [1, 2, 3], "x": [2, 4, 6], "category": ["a", "b", "a"]})
    out, _, _ = execute_frame(
        frame,
        "conditions",
        {
            "conditions": [
                {"column": "x", "operator": "ge", "value": 4},
                {"column": "category", "operator": "eq", "value": "a"},
            ]
        },
    )
    assert out.id.tolist() == [3]
    out, _, _ = execute_frame(
        frame,
        "combine",
        {"dataset": "other", "left_on": "id", "right_on": "id"},
        {"other": pd.DataFrame({"id": [2], "label": ["B"]})},
    )
    assert out.label.dropna().tolist() == ["B"]
    with pytest.raises(ValueError):
        execute_frame(
            frame,
            "combine",
            {"dataset": "other", "left_on": "id", "right_on": "id"},
            {"other": pd.DataFrame({"id": [2, 2]})},
        )


def test_recipe_templates_preserve_types_and_require_bindings():
    assert resolve_parameters({"x": "{{seed:42}}", "y": ["{{target}}"]}, {"target": "label"}) == {
        "x": 42,
        "y": ["label"],
    }
    with pytest.raises(ValueError):
        resolve_parameters("{{target}}", {})


def test_query_version_workflow_recipe_and_chart_persistence(lab_client):
    client, ds, _ = lab_client
    path = "/api/v1/lab/datasets/" + ds["id"]
    service = Workbench(api_module.WORKSPACE)
    v = client.post(path + "/versions", json={"name": "Before"}).json()
    q = client.post(
        path + "/query",
        json={"conditions": [{"column": "age", "operator": "ge", "value": 30}], "remember": True},
    )
    assert q.status_code == 200, q.text
    assert q.json()["positions"] == [1, 2]
    assert client.get(path + "/queries").json()["items"]
    recipe = client.post(
        "/api/v1/lab/recipes",
        json={
            "name": "Template",
            "steps": [
                {
                    "operation": "derive",
                    "parameters": {"name": "{{feature}}", "expression": "age * 2"},
                }
            ],
        },
    ).json()
    update = client.post("/api/v1/lab/recipes", json={**recipe, "name": "Edited"})
    assert update.status_code == 201, update.text
    run = client.post(
        "/api/v1/lab/recipes/" + recipe["id"] + "/run",
        json={"dataset_id": ds["id"], "revision": 0, "bindings": {"feature": "double"}},
    )
    assert run.status_code == 200, run.text
    _drain_worker()
    diff = client.get(path + "/compare", params={"left": v["id"]})
    assert diff.status_code == 200, diff.text
    assert diff.json()["columns_added"] == ["double"]
    wf = client.post(
        f"/api/v1/lab/projects/{ds['project_id']}/workflows",
        json={"name": "Saved", "steps": recipe["steps"]},
    )
    assert wf.status_code == 200, wf.text
    chart = client.post(
        path + "/charts", json={"name": "Age", "definition": {"kind": "histogram", "x": "age"}}
    )
    assert chart.status_code == 200, chart.text
    assert len(Workbench(api_module.WORKSPACE).charts(ds["id"])) == 1
    assert service.dataset(ds["id"])["root_key"] == ds["root_key"]


def test_preview_modes_and_join_snapshot_export(lab_client):
    client, ds, _ = lab_client
    service = Workbench(api_module.WORKSPACE)
    path = "/api/v1/lab/datasets/" + ds["id"]
    for mode in ["first", "random", "representative", "selected"]:
        r = client.post(
            path + "/preview", json={"operation": "profile", "mode": mode, "selected": [2]}
        )
        assert r.status_code == 200, r.text
    raw = b"age,region\n20,A\n30,B\n40,C\n"
    client.post(
        f"/api/v1/projects/{ds['project_id']}/assets",
        files={"file": ("lookup.csv", raw, "text/csv")},
    )
    _drain_worker()
    sources = client.get(f"/api/v1/projects/{ds['project_id']}/tabular").json()["items"]
    source = next(s for s in sources if s["name"] == "lookup")
    other = service.adopt(source["id"])
    result = service.enqueue(
        ds["id"],
        [
            {
                "operation": "combine",
                "parameters": {"dataset": other["id"], "left_on": "age", "right_on": "age"},
            }
        ],
        0,
    )
    _drain_worker()
    run = service.run_record(result["run_id"])
    assert run["state"] == "completed", run
    assert run["data"]["inputs"][other["id"]] == other["head_key"]
    response = client.get(path + "/export?bundle=true")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert any(n.startswith("inputs/") for n in z.namelist())
        code = z.read("workflow.py").decode()
        assert "inputs/" in code
        # Replay generated code against the exact files, not current catalog heads.
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            z.extractall(folder)
            subprocess.run(
                [sys.executable, "workflow.py"], cwd=folder, check=True, capture_output=True
            )
            from pathlib import Path

            pd.testing.assert_frame_equal(
                pd.read_parquet(Path(folder) / "dataset.parquet"),
                pd.read_parquet(Path(folder) / "output.parquet"),
            )


def test_failed_workflow_reuses_successful_checkpoint(lab_client, monkeypatch):
    from mediasensei import operations

    _client, ds, _ = lab_client
    service = Workbench(api_module.WORKSPACE)
    steps = [
        {"operation": "derive", "parameters": {"name": "doubled", "expression": "age * 2"}},
        {"operation": "sort", "parameters": {"column": "age"}},
    ]
    original = operations.execute_frame
    calls = []

    def interrupted(frame, operation, params, inputs=None):
        calls.append(operation)
        if operation == "sort":
            raise ValueError("Simulated interruption")
        return original(frame, operation, params, inputs)

    result = service.enqueue(ds["id"], steps, 0)
    monkeypatch.setattr(operations, "execute_frame", interrupted)
    with pytest.raises(ValueError):
        service.execute_run(result["run_id"])
    assert service.dataset(ds["id"])["revision"] == 0
    assert len(service.run_record(result["run_id"])["data"]["checkpoints"]) == 1

    def resumed(frame, operation, params, inputs=None):
        assert operation != "derive", "Successful step should be restored from checkpoint"
        return original(frame, operation, params, inputs)

    monkeypatch.setattr(operations, "execute_frame", resumed)
    assert service.execute_run(result["run_id"])["progress"]["completed_steps"] == 2
    assert service.dataset(ds["id"])["revision"] == 1


def test_function_search_and_asset_operation_adapters(lab_client):
    client, ds, _ = lab_client
    result = client.get("/api/v1/lab/functions?q=groupby")
    assert result.status_code == 200, result.text
    assert any("groupby" in r["name"] for r in result.json()["items"])
    result = client.get("/api/v1/lab/search?q=heat%20map")
    assert result.status_code == 200, result.text
    assert any(r.get("operation") == "correlation" for r in result.json()["items"])
    document = client.post(
        f"/api/v1/projects/{ds['project_id']}/assets",
        files={"file": ("note.txt", b"A useful sentence about data.", "text/plain")},
    )
    assert document.status_code == 202, document.text
    _drain_worker()
    assets = client.get(f"/api/v1/projects/{ds['project_id']}/assets").json()["items"]
    asset = next(a for a in assets if a["original_filename"] == "note.txt")
    run = client.post(
        f"/api/v1/lab/projects/{ds['project_id']}/asset-operations",
        json={"operation": "document.index", "asset_ids": [asset["id"]]},
    )
    assert run.status_code == 202, run.text
    _drain_worker()
    job = client.get("/api/v1/jobs/" + run.json()["job_id"]).json()
    assert job["state"] == "completed", job


def test_operation_cacheability_contract_is_respected(lab_client,monkeypatch):
    from dataclasses import replace

    from mediasensei import operations
    _client,ds,_=lab_client;service=Workbench(api_module.WORKSPACE)
    monkeypatch.setitem(operations.REGISTRY._operations,"profile",replace(operations.REGISTRY.get("profile"),cacheable=False))
    for _ in range(2):
        queued=service.enqueue(ds["id"],[{"operation":"profile","parameters":{}}],0)
        result=service.execute_run(queued["run_id"])
        assert result["cache_hit"] is False
    with service.catalog.connect() as db:
        assert db.execute("SELECT count(*) FROM operation_cache").fetchone()[0]==0
