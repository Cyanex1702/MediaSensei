"""Failures found by the September 2026 independent QA pass."""
import io
import json

import pandas as pd
import pytest
from mediasensei.operations import execute_frame, profile
from test_real_app_flow import _client, _drain_worker


def test_nested_cells_can_be_profiled_and_deduplicated():
    frame = pd.DataFrame({"tags": [["a"], ["a"], ["b"]], "meta": [{"x": 1}, {"x": 1}, {"x": 2}]})
    result = profile(frame)
    assert result["duplicates"] == 1
    assert result["columns"][0]["unique"] == 2
    cleaned, _, _ = execute_frame(frame, "drop_duplicates", {})
    assert len(cleaned) == 2
    assert cleaned.iloc[0]["meta"] == {"x": 1}
    assert len(frame) == 3


@pytest.mark.parametrize("nested", [False, True])
def test_parquet_import_overview_and_rows_are_json_safe(tmp_path, nested):
    client = _client(tmp_path)
    project = client.post("/api/v1/projects", json={"name": "QA edge data"}).json()["id"]
    frame = (pd.DataFrame({"tags": [["a"], ["a"]], "meta": [{"x": 1}, {"x": 1}]})
             if nested else pd.DataFrame({"value": [float("inf"), float("-inf"), float("nan"), 1.0]}))
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    uploaded = client.post(f"/api/v1/projects/{project}/assets", files={"file": ("edge.parquet", stream.getvalue())})
    assert uploaded.status_code == 202, uploaded.text
    _drain_worker()
    sources = client.get(f"/api/v1/projects/{project}/tabular")
    assert sources.status_code == 200, sources.text
    source = sources.json()["items"][0]
    adopted = client.post("/api/v1/lab/datasets/from-table/" + source["id"])
    assert adopted.status_code == 201, adopted.text
    path = "/api/v1/lab/datasets/" + adopted.json()["id"]
    for endpoint in [path, path + "/rows"]:
        result = client.get(endpoint)
        assert result.status_code == 200, result.text
        json.dumps(result.json(), allow_nan=False)
