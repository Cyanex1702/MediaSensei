import io
import sqlite3

import pytest
from mediasensei.infrastructure.acquisition_planning import (
    MetadataRelevanceEvaluator,
    RuleBasedPromptPlanner,
)
from test_real_app_flow import _client, _drain_worker


def test_relevance_does_not_trust_query():
    spec = RuleBasedPromptPlanner().plan("Find 10 images of red foxes")
    decision = MetadataRelevanceEvaluator().evaluate(
        spec, {"title": "Passenger airplane", "description": "Airport runway", "query": "red foxes"}
    )
    assert decision.decision.value == "review"


def test_license_is_enforced_in_plan():
    spec = RuleBasedPromptPlanner().plan("Find 10 images of red foxes, CC0 only")
    assert spec.allowed_licenses == ("cc0",)
    assert "CC0" not in spec.topic


@pytest.mark.parametrize(
    "prompt",
    [
        "Find 10 CSV datasets about houses",
        "Find 10 images of foxes, exclude people",
        "Find public domain fox photos",
    ],
)
def test_unsupported_constraints_fail_explicitly(prompt):
    with pytest.raises(ValueError):
        RuleBasedPromptPlanner().plan(prompt)


def test_database_source_selection_and_preserved_provenance(tmp_path):
    client = _client(tmp_path)
    pid = client.post("/api/v1/projects", json={"name": "Selection"}).json()["id"]
    db = tmp_path / "two.db"
    with sqlite3.connect(db) as c:
        c.execute("create table accounts(name text)")
        c.execute("insert into accounts values ('Alice')")
        c.execute("create table sales(amount integer)")
        c.execute("insert into sales values (999)")
    raw = db.read_bytes()
    options = client.post("/api/v1/import-options", files={"file": ("two.db", raw)})
    assert options.status_code == 200, options.text
    assert options.json()["names"] == ["accounts", "sales"]
    r = client.post(f"/api/v1/projects/{pid}/tabular?table=sales", files={"file": ("two.db", raw)})
    assert r.status_code == 202, r.text
    _drain_worker()
    ds = client.get("/api/v1/tabular/" + r.json()["dataset_id"]).json()
    assert ds["options"]["table"] == "sales"
    assert ds["profile"]["sample"] == [{"amount": 999}]


def test_workbook_selection(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "First"
    wb.active.append(["id"])
    wb.active.append([1])
    ws = wb.create_sheet("Second")
    ws.append(["value"])
    ws.append([42])
    out = io.BytesIO()
    wb.save(out)
    client = _client(tmp_path)
    r = client.post("/api/v1/import-options", files={"file": ("book.xlsx", out.getvalue())})
    assert r.status_code == 200, r.text
    assert r.json() == {"kind": "sheet", "names": ["First", "Second"]}


def test_malformed_csv_job_fails_without_normalized_data(tmp_path):
    client = _client(tmp_path)
    pid = client.post("/api/v1/projects", json={"name": "Bad CSV"}).json()["id"]
    r = client.post(
        f"/api/v1/projects/{pid}/assets",
        files={"file": ("bad.csv", b"name,amount\nAlice,1\nBob,2,extra\n")},
    )
    assert r.status_code == 202
    _drain_worker()
    jobs = client.get(f"/api/v1/jobs?project_id={pid}").json()["items"]
    assert jobs[0]["counts"]["failed"] == 1
    ds = client.get(f"/api/v1/projects/{pid}/tabular").json()["items"][0]
    assert not ds.get("normalized_object_key")


def test_delimiter_and_identifiers_survive_worker(tmp_path):
    client = _client(tmp_path)
    pid = client.post("/api/v1/projects", json={"name": "Identifiers"}).json()["id"]
    r = client.post(
        f"/api/v1/projects/{pid}/tabular?delimiter=%3B&all_text=true",
        files={"file": ("ids.csv", b"id;amount\n00123;10\n")},
    )
    assert r.status_code == 202, r.text
    _drain_worker()
    ds = client.get("/api/v1/tabular/" + r.json()["dataset_id"]).json()
    assert ds["options"] == {"delimiter": ";", "all_text": True}
    assert ds["profile"]["sample"] == [{"id": "00123", "amount": "10"}]


@pytest.mark.parametrize(
    "actual,allowed,expected",
    [
        ("CC0 1.0", ("cc0",), True),
        ("BY 4.0", ("cc-by",), True),
        ("CC BY-SA 4.0", ("cc-by-sa",), True),
        ("BY-NC 4.0", ("cc-by",), False),
        ("BY-SA 4.0", ("cc-by",), False),
        ("BY 2.0", ("cc-by 4.0",), False),
        ("unknown", ("cc0",), False),
        ("", ("cc0",), False),
    ],
)
def test_provider_license_labels_preserve_restrictions(actual, allowed, expected):
    from mediasensei.infrastructure.acquisition import license_allowed

    assert license_allowed(actual, allowed) is expected
