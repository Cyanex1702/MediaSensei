from test_operations import lab_client as lab_client  # noqa: PLC0414 - pytest fixture re-export


def test_saved_contract_counts_and_dictionary(lab_client):
    client, ds, _ = lab_client
    url = "/api/v1/contracts/" + ds["id"]
    contract = {
        "rules": [
            {"column": "income", "check": "required", "value": ""},
            {"column": "age", "check": "unique", "value": ""},
        ],
        "dictionary": {"income": "Annual income in USD"},
    }
    r = client.put(url, json=contract)
    assert r.status_code == 200, r.text
    assert client.get(url).json() == contract
    result = client.post(url + "/evaluate").json()
    assert result["failed_rows"] == 3
    assert result["revision"] == 0
    assert result["passed"] is False
    assert result["dictionary"]["income"] == "Annual income in USD"
    assert len(result["offending_rows"]) == 3


def test_invalid_contract_does_not_replace_saved(lab_client):
    client, ds, _ = lab_client
    url = "/api/v1/contracts/" + ds["id"]
    assert (
        client.put(url, json={"rules": [{"column": "missing", "check": "required"}]}).status_code
        == 422
    )
    assert client.get(url).json()["rules"] == []


def test_backup_restore_integrity_and_no_overwrite(tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import pytest
    from workspace_backup import backup, restore

    source = tmp_path / "source"
    source.mkdir()
    (source / "object.txt").write_text("immutable")
    archive = backup(source, tmp_path / "backup.zip")
    target = restore(archive, tmp_path / "restored")
    assert (target / "object.txt").read_text() == "immutable"
    with pytest.raises(ValueError):
        restore(archive, target)


def test_collections_survive_reload_and_manifest(lab_client):
    client, ds, _ = lab_client
    pid = ds["project_id"]
    url = f"/api/v1/workspace/projects/{pid}"
    saved = client.post(
        url + "/collections", json={"name": "Tables", "query": "data", "modality": "tabular"}
    )
    assert saved.status_code == 201, saved.text
    assert client.get(url + "/collections").json()["items"][0]["query"] == "data"
    manifest = client.get(url + "/manifest")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["datasets"][0]["id"] == ds["id"]
    storage = client.get("/api/v1/workspace/storage")
    assert storage.status_code == 200
    assert storage.json()["stored_objects"] > 0
    assert client.delete(url + "/collections/" + saved.json()["id"]).status_code == 200
    assert client.get(url + "/collections").json()["items"] == []


def test_catalog_backup_includes_committed_wal_and_restores(tmp_path):
    import sqlite3
    import sys
    from contextlib import closing
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from workspace_backup import backup, restore

    source = tmp_path / "source"
    source.mkdir()
    with closing(sqlite3.connect(source / "catalog.db")) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records(value TEXT)")
        db.execute("INSERT INTO records VALUES ('retained')")
        db.commit()
        archive = backup(source, tmp_path / "catalog.zip")
    restored = restore(archive, tmp_path / "restored")
    with closing(sqlite3.connect(restored / "catalog.db")) as db:
        assert db.execute("SELECT value FROM records").fetchone()[0] == "retained"
