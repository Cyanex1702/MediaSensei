"""Saved data contracts and a human-authored data dictionary."""

from __future__ import annotations

import json
from typing import Literal

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .lab import LabRoute, wb

router = APIRouter(prefix="/api/v1/contracts", route_class=LabRoute)


class Rule(BaseModel):
    column: str = Field(min_length=1, max_length=300)
    check: Literal["required", "unique", "minimum", "maximum", "allowed", "numeric"]
    value: str = Field(default="", max_length=10000)


class Contract(BaseModel):
    rules: list[Rule] = Field(default_factory=list, max_length=200)
    dictionary: dict[str, str] = Field(default_factory=dict, max_length=1000)


def setup(service):
    with service.catalog.connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS data_contracts(dataset_id TEXT PRIMARY KEY, document TEXT NOT NULL)"
        )


@router.get("/{dataset_id}")
def get_contract(dataset_id: str):
    service = wb()
    service.dataset(dataset_id)
    setup(service)
    with service.catalog.connect() as db:
        row = db.execute(
            "SELECT document FROM data_contracts WHERE dataset_id=?", (dataset_id,)
        ).fetchone()
    return json.loads(row[0]) if row else {"rules": [], "dictionary": {}}


@router.put("/{dataset_id}")
def save_contract(dataset_id: str, payload: Contract):
    service = wb()
    ds = service.dataset(dataset_id)
    setup(service)
    frame = service.frame(ds["head_key"], sample=1)
    names = set(frame.columns)
    if any(rule.column not in names for rule in payload.rules) or any(
        name not in names for name in payload.dictionary
    ):
        raise ValueError("Choose columns from the current dataset")
    for rule in payload.rules:
        if rule.check in {"minimum", "maximum"}:
            import math

            if not math.isfinite(float(rule.value)):
                raise ValueError("Bounds must be finite numbers")
    document = payload.model_dump()
    with service.catalog.connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO data_contracts VALUES (?,?)", (dataset_id, json.dumps(document))
        )
    return document


@router.post("/{dataset_id}/evaluate")
def evaluate_contract(dataset_id: str):
    service = wb()
    ds = service.dataset(dataset_id)
    frame = service.frame(ds["head_key"])
    contract = get_contract(dataset_id)
    results = []
    bad = pd.Series(False, index=frame.index)
    for rule in contract["rules"]:
        name = rule["column"]
        if name not in frame:
            raise ValueError(f"Contract column no longer exists: {name}")
        values = frame[name]
        kind = rule["check"]
        value = rule["value"]
        if kind == "required":
            failed = values.isna() | values.astype(str).str.strip().eq("")
        elif kind == "unique":
            from mediasensei.cell_values import comparison_value

            failed = values.map(comparison_value).duplicated(keep=False)
        elif kind == "allowed":
            failed = values.notna() & ~values.astype(str).isin(
                [v.strip() for v in value.split(",")]
            )
        else:
            numeric = pd.to_numeric(values, errors="coerce")
            failed = values.notna() & numeric.isna()
            if kind == "minimum":
                failed = failed | (numeric < float(value))
            elif kind == "maximum":
                failed = failed | (numeric > float(value))
        bad = bad | failed
        results.append({**rule, "failed_rows": int(failed.sum())})
    from mediasensei.operations import records

    return {
        "dataset_id": dataset_id,
        "revision": ds["revision"],
        "source_key": ds["head_key"],
        "row_count": len(frame),
        "failed_rows": int(bad.sum()),
        "passed": not bool(bad.any()),
        "rules": results,
        "sample_limit": 100,
        "offending_rows": records(frame.loc[bad].head(100)),
        "dictionary": contract["dictionary"],
    }
