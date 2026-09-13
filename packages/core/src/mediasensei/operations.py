"""Local operation engine. The API and worker are adapters to this module."""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from mediasensei import __version__
from mediasensei.domain.jobs import ProcessorSpec, WorkItem
from mediasensei.domain.operations import REGISTRY
from mediasensei.infrastructure.catalog import Catalog
from mediasensei.infrastructure.jobs import JobQueue
from mediasensei.infrastructure.storage import ContentAddressedStore
from mediasensei.infrastructure.tabular import TabularEngine

MAX_ROWS = 200_000
MAX_BYTES = 256 * 1024 * 1024
REPORTS = {
    "profile",
    "missing",
    "correlation",
    "distribution",
    "statistics",
    "outliers",
    "quality",
    "chart",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_datasets(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), source_id TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, root_key TEXT NOT NULL, head_key TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, lineage_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS lab_versions(
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES lab_datasets(id), name TEXT NOT NULL,
 manifest_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operation_runs(
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES lab_datasets(id), job_id TEXT,
 state TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operation_cache(cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lab_recipes(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, steps_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_operation_runs_dataset ON operation_runs(dataset_id, created_at);
"""


def now():
    return datetime.now(UTC).isoformat()


def clean(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def parameters(operation, supplied, columns):
    definition = REGISTRY.get(operation)
    unknown = set(supplied) - set(definition.parameter_schema)
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
    result = {}
    for name, schema in definition.parameter_schema.items():
        value = supplied.get(name, schema.get("default"))
        kind = schema["type"]
        if kind == "columns":
            value = columns if value is None else value
            if (
                not isinstance(value, list)
                or not value
                or len(set(value)) != len(value)
                or any(c not in columns for c in value)
            ):
                raise ValueError("Select at least one valid, distinct column.")
        elif kind == "column":
            if schema.get("optional") and value in (None, ""):
                value = None
            elif value not in columns:
                raise ValueError(f"Select a valid column for {schema['title']}.")
        elif kind == "enum" and value not in schema["choices"]:
            raise ValueError(f"Invalid {schema['title']}.")
        elif kind == "number":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not np.isfinite(value)
            ):
                raise ValueError(f"{schema['title']} must be a finite number.")
            if not schema.get("minimum", -np.inf) <= value <= schema.get("maximum", np.inf):
                raise ValueError(f"{schema['title']} is outside the allowed range.")
        elif kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{schema['title']} must be true or false.")
        elif kind == "string" and (not isinstance(value, str) or len(value) > 1000):
            raise ValueError(f"{schema['title']} must be text of at most 1000 characters.")
        elif kind == "json":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{schema['title']} must contain valid JSON.") from e
            if not isinstance(value, (list, dict)) or len(json.dumps(value)) > 50000:
                raise ValueError(
                    f"{schema['title']} must be a JSON list/object of at most 50,000 characters."
                )
        elif kind == "dataset" and (not isinstance(value, str) or not value):
            raise ValueError("Choose a second dataset.")
        result[name] = value
    if operation == "split":
        if result["train"] + result["validation"] >= 1:
            raise ValueError("Train and validation fractions must leave a non-empty test fraction.")
        if result["strategy"] != "random" and not result["column"]:
            raise ValueError("Select a class/group column for this split strategy.")
        if result["seed"] != int(result["seed"]):
            raise ValueError("Random seed must be an integer.")
    return result


def profile(frame):
    columns = []
    findings = []
    for name in frame:
        series = frame[name]
        numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
        missing = int(series.isna().sum())
        unique = int(series.nunique())
        item = {
            "name": name,
            "dtype": str(series.dtype),
            "missing": missing,
            "unique": unique,
            "numeric": numeric,
            "samples": records(pd.DataFrame({"value": series.dropna().head(5)})),
        }
        if numeric:
            values = series.replace([np.inf, -np.inf], np.nan).dropna()
            stats = {
                key: None if pd.isna(value) else float(value)
                for key, value in {
                    "mean": values.mean(),
                    "median": values.median(),
                    "std": values.std(),
                    "min": values.min(),
                    "max": values.max(),
                }.items()
            }
            item.update(stats)
            q1, q3 = values.quantile(0.25), values.quantile(0.75)
            item["outliers"] = int(
                ((values < q1 - 1.5 * (q3 - q1)) | (values > q3 + 1.5 * (q3 - q1))).sum()
            )
        columns.append(item)
        if missing:
            findings.append(
                {
                    "title": f"{name}: {missing:,} missing values",
                    "reason": "Missing features may prevent training or bias summaries.",
                    "operation": "fill_missing",
                    "parameters": {"columns": [name], "strategy": "median" if numeric else "mode"},
                }
            )
        if numeric:
            invalid = int(np.isinf(pd.to_numeric(series, errors="coerce").astype(float)).sum())
            if invalid:
                findings.append(
                    {
                        "title": f"{name}: {invalid} infinite values",
                        "reason": "Infinite values invalidate many statistics and estimators.",
                        "operation": "quality",
                        "parameters": {},
                    }
                )
            skew = float(series.skew()) if len(series.dropna()) > 2 else 0
            if np.isfinite(skew) and abs(skew) > 1:
                findings.append(
                    {
                        "title": f"{name}: skewness {skew:.2f}",
                        "reason": "A skewed distribution may benefit from a log transform; inspect its range first.",
                        "operation": "chart",
                        "parameters": {"kind": "histogram", "x": name},
                    }
                )
        elif 1 < unique <= 30 and len(series):
            counts = series.value_counts()
            if len(counts) > 1 and counts.iloc[0] / max(counts.iloc[-1], 1) > 4:
                findings.append(
                    {
                        "title": f"{name}: category imbalance ({counts.iloc[0]} vs {counts.iloc[-1]})",
                        "reason": "If this is the target, stratify splits so rare classes remain represented.",
                        "operation": "split",
                        "parameters": {"strategy": "stratified", "column": name},
                    }
                )
        if unique > 100 and unique / max(len(series), 1) > 0.8:
            findings.append(
                {
                    "title": f"{name}: high cardinality ({unique} values)",
                    "reason": "Identifier-like columns can overfit models and create very wide encodings.",
                    "operation": "statistics",
                    "parameters": {"columns": [name], "method": "frequency"},
                }
            )
        if unique <= 1:
            findings.append(
                {
                    "title": f"{name}: constant column",
                    "reason": "A constant feature cannot distinguish samples.",
                    "operation": "drop_columns",
                    "parameters": {"columns": [name]},
                }
            )
    duplicates = int(frame.duplicated().sum())
    if duplicates:
        findings.append(
            {
                "title": f"{duplicates:,} duplicate rows",
                "reason": "Copies may overweight examples and leak across splits.",
                "operation": "drop_duplicates",
                "parameters": {},
            }
        )
    if sum(c["numeric"] for c in columns) >= 2:
        findings.append(
            {
                "title": "Inspect numeric relationships",
                "reason": "At least two numeric features are available for correlation analysis.",
                "operation": "correlation",
                "parameters": {},
            }
        )
    numeric_frame = frame.select_dtypes(include="number")
    if 2 <= len(numeric_frame.columns) <= 60:
        corr = numeric_frame.corr().abs()
        for i, c in enumerate(corr.columns):
            for other in corr.columns[i + 1 :]:
                if corr.loc[c, other] > 0.95:
                    findings.append(
                        {
                            "title": f"{c} / {other}: correlation {corr.loc[c, other]:.3f}",
                            "reason": "Strongly related predictors may be redundant or target-derived. Inspect before excluding.",
                            "operation": "correlation",
                            "parameters": {},
                        }
                    )
    if "_split" in frame:
        features = frame.drop(columns=["_split"])
        hashes = pd.util.hash_pandas_object(features, index=False)
        overlaps = int(
            pd.DataFrame({"hash": hashes, "split": frame["_split"]})
            .groupby("hash")["split"]
            .nunique()
            .gt(1)
            .sum()
        )
        if overlaps:
            findings.append(
                {
                    "title": f"{overlaps} identical samples cross split boundaries",
                    "reason": "Evaluation data overlaps training data. Remove duplicates before splitting.",
                    "operation": "drop_duplicates",
                    "parameters": {"columns": list(features.columns)},
                }
            )
    return {
        "rows": len(frame),
        "column_count": len(frame.columns),
        "columns": columns,
        "duplicates": duplicates,
        "memory_bytes": int(frame.memory_usage(deep=True).sum()),
        "findings": findings,
    }


def execute_frame(frame, operation, supplied, inputs=None):
    """Pure operation: copy input; no I/O or arbitrary code evaluation."""
    p = parameters(operation, supplied, list(frame.columns))
    output = frame.copy(deep=True)
    report = None
    selected = p.get("columns", [])
    if operation in {"profile", "missing"}:
        report = {
            "kind": "missing",
            "title": "Missing values",
            "values": [{"name": c, "value": int(frame[c].isna().sum())} for c in frame],
        }
    elif operation == "correlation":
        numeric = frame.select_dtypes(include="number").drop(columns=["_split"], errors="ignore")
        if len(numeric.columns) < 2:
            raise ValueError("Correlation requires at least two numeric columns.")
        if len(numeric.columns) > 60:
            raise ValueError("Select a dataset with at most 60 numeric columns for the heatmap.")
        corr = numeric.corr()
        report = {
            "kind": "heatmap",
            "title": "Pearson correlation",
            "columns": list(corr.columns),
            "values": records(corr),
        }
    elif operation == "distribution":
        series = frame[p["column"]]
        if pd.api.types.is_numeric_dtype(series) and series.nunique() > 20:
            values = series.replace([np.inf, -np.inf], np.nan).dropna()
            counts, edges = np.histogram(values, bins=20)
            values = [
                {"name": f"{edges[i]:.3g}–{edges[i + 1]:.3g}", "value": int(n)}
                for i, n in enumerate(counts)
            ]
        else:
            values = [
                {"name": "(missing)" if pd.isna(k) else str(k), "value": int(v)}
                for k, v in series.value_counts(dropna=False).head(50).items()
            ]
        report = {"kind": "bar", "title": p["column"], "values": values}
    elif operation == "fill_missing":
        for column in selected:
            series = output[column]
            method = p["strategy"]
            if method in {"mean", "median"}:
                if not pd.api.types.is_numeric_dtype(series):
                    raise ValueError(f"{column} is not numeric; use mode or a constant.")
                output[column] = series.astype(float).fillna(getattr(series, method)())
            elif method == "mode":
                modes = series.mode()
                if modes.empty:
                    raise ValueError(f"{column} contains only missing values. Use a constant.")
                output[column] = series.fillna(modes.iloc[0])
            elif method == "constant":
                value = float(p["value"]) if pd.api.types.is_numeric_dtype(series) else p["value"]
                output[column] = series.fillna(value)
            else:
                output[column] = series.ffill() if method == "forward" else series.bfill()
    elif operation == "drop_missing":
        output = output.dropna(subset=selected)
    elif operation == "drop_duplicates":
        output = output.drop_duplicates(subset=selected)
    elif operation == "drop_columns":
        if len(selected) == len(output.columns):
            raise ValueError("Keep at least one column.")
        output = output.drop(columns=selected)
    elif operation in {"scale", "clip"}:
        if any(not pd.api.types.is_numeric_dtype(output[c]) for c in selected):
            raise ValueError("Select only numeric columns.")
        values = output[selected].astype(float)
        if operation == "clip":
            output[selected] = values.clip(
                values.quantile(p["lower"]), values.quantile(p["upper"]), axis=1
            )
        else:
            method = p["method"]
            center = (
                values.mean()
                if method == "standard"
                else values.min()
                if method == "minmax"
                else values.median()
            )
            width = (
                values.std(ddof=0)
                if method == "standard"
                else values.max() - values.min()
                if method == "minmax"
                else values.quantile(0.75) - values.quantile(0.25)
            )
            output[selected] = (values - center) / width.replace(0, 1)
    elif operation == "encode":
        if (
            any(output[c].nunique() > 100 for c in selected)
            or sum(output[c].nunique() + 1 for c in selected) > 500
        ):
            raise ValueError(
                "Encoding is limited to 100 categories per column and 500 output indicators."
            )
        output = pd.get_dummies(output, columns=selected, dummy_na=True, dtype=int)
        if output.columns.duplicated().any():
            raise ValueError(
                "Encoding would create duplicate column names. Rename overlapping columns first."
            )
    elif operation == "filter":
        series, operator, value = output[p["column"]], p["operator"], p["value"]
        if operator in {"greater", "less"}:
            value = float(value)
            mask = (
                pd.to_numeric(series, errors="raise") > value
                if operator == "greater"
                else pd.to_numeric(series, errors="raise") < value
            )
        elif operator in {"is_null", "not_null"}:
            mask = series.isna() if operator == "is_null" else series.notna()
        elif operator == "contains":
            mask = series.astype("string").str.contains(value, regex=False, na=False)
        else:
            mask = (
                series.astype("string").eq(value)
                if operator == "equals"
                else series.astype("string").ne(value)
            )
        output = output.loc[mask.fillna(False)]
    elif operation == "sort":
        output = output.sort_values(p["column"], ascending=not p["descending"], kind="stable")
    elif operation == "rename":
        if not p["name"].strip() or p["name"] in output.columns:
            raise ValueError("Choose a non-empty, unique column name.")
        output = output.rename(columns={p["column"]: p["name"]})
    elif operation == "cast":
        column = p["column"]
        output[column] = (
            output[column].astype("string")
            if p["dtype"] == "string"
            else pd.to_numeric(output[column], errors="raise")
            if p["dtype"] == "number"
            else pd.to_datetime(output[column], errors="raise", utc=True)
        )
    elif operation == "split":
        if "_split" in output:
            raise ValueError("A split already exists. Drop _split before creating a new split.")
        rng = np.random.default_rng(int(p["seed"]))
        output = output.reset_index(drop=True)
        labels = np.full(len(output), "test", dtype=object)
        if p["strategy"] in {"group", "source"}:
            groups = output[p["column"]].fillna("__missing_group__").astype(str)
            keys = np.array(groups.unique(), dtype=object)
            rng.shuffle(keys)
            a, b = int(len(keys) * p["train"]), int(len(keys) * (p["train"] + p["validation"]))
            mapping = {
                key: "train" if i < a else "validation" if i < b else "test"
                for i, key in enumerate(keys)
            }
            labels = groups.map(mapping).to_numpy()
        else:
            groups = (
                output.groupby(p["column"], dropna=False, sort=False).indices.values()
                if p["strategy"] == "stratified"
                else [np.arange(len(output))]
            )
            for indices in groups:
                indices = np.array(indices, copy=True)
                rng.shuffle(indices)
                a, b = (
                    int(len(indices) * p["train"]),
                    int(len(indices) * (p["train"] + p["validation"])),
                )
                labels[indices[:a]] = "train"
                labels[indices[a:b]] = "validation"
        output["_split"] = labels
        report = {
            "kind": "bar",
            "title": "Split distribution",
            "values": [
                {"name": str(k), "value": int(v)}
                for k, v in output["_split"].value_counts().items()
            ],
        }
    elif operation in REGISTRY._executors:
        output, report = REGISTRY._executors[operation](output, p, inputs or {})
    else:
        from mediasensei.tabular_operations import run_extra

        output, report = run_extra(frame, operation, p, inputs)
    if len(output) > MAX_ROWS or len(output.columns) > 1000:
        raise ValueError("Result exceeds the 200,000 row / 1,000 column working limit.")
    if output.columns.duplicated().any():
        raise ValueError("The result contains duplicate column names.")
    if report is not None:
        report["definition"]={"operation":operation,"parameters":p}
    return output.reset_index(drop=True), report, p


from mediasensei.workflows import WorkflowFeatures


class Workbench(WorkflowFeatures):
    """In-process SDK. Shares catalog, storage and jobs with REST and CLI."""

    def __init__(self, workspace):
        self.catalog = workspace if isinstance(workspace, Catalog) else Catalog(workspace)
        self.store = ContentAddressedStore(self.catalog.workspace)
        self.engine = TabularEngine(self.store)
        with self.catalog.connect() as db:
            db.executescript(SCHEMA)
            self.migrate_features(db)
            if "lineage_json" not in {
                row[1] for row in db.execute("PRAGMA table_info(lab_datasets)")
            }:
                db.execute(
                    "ALTER TABLE lab_datasets ADD COLUMN lineage_json TEXT NOT NULL DEFAULT '[]'"
                )

    def adopt(self, source_id):
        source = self.catalog.get_tabular_dataset(source_id)
        with self.catalog.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO lab_datasets(id,project_id,source_id,name,root_key,head_key,revision,created_at,updated_at) VALUES (?,?,?,?,?,?,0,?,?)",
                (
                    str(uuid4()),
                    source["project_id"],
                    source_id,
                    source["name"],
                    source["normalized_object_key"],
                    source["normalized_object_key"],
                    now(),
                    now(),
                ),
            )
            row = db.execute(
                "SELECT * FROM lab_datasets WHERE source_id=?", (source_id,)
            ).fetchone()
        return dict(row)

    def datasets(self, project_id):
        with self.catalog.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM lab_datasets WHERE project_id=? ORDER BY created_at DESC",
                    (project_id,),
                )
            ]

    def dataset(self, dataset_id):
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM lab_datasets WHERE id=?", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError("Dataset not found.")
        return dict(row)

    def frame(self, key, sample=None):
        path = self.store.resolve(key)
        parquet = pq.ParquetFile(path)
        if sample:
            batches = parquet.iter_batches(batch_size=sample)
            batch = next(batches, None)
            return (
                batch.to_pandas()
                if batch is not None
                else parquet.schema_arrow.empty_table().to_pandas()
            )
        if parquet.metadata.num_rows > MAX_ROWS or path.stat().st_size > MAX_BYTES:
            raise ValueError(
                "This operation supports at most 200,000 rows and 256 MiB of Parquet. Use a bounded export or DuckDB query first."
            )
        frame = parquet.read().to_pandas()
        if frame.memory_usage(deep=True).sum() > MAX_BYTES * 4:
            raise ValueError("Decoded data exceeds the 1 GiB working-memory allowance.")
        return frame

    def overview(self, dataset_id):
        dataset = self.dataset(dataset_id)
        return {"dataset": dataset, "profile": self.cached_profile(dataset["head_key"])}

    def preview(
        self, dataset_id, operation, supplied, sample=100, mode="first", seed=42, selected=None
    ):
        dataset = self.dataset(dataset_id)
        before = self.sample_frame(dataset["head_key"], sample, mode, seed, selected)
        inputs = self.capture_inputs(dataset_id, [{"operation": operation, "parameters": supplied}])
        after, chart, p = execute_frame(
            before,
            operation,
            supplied,
            {k: self.frame(v, sample=sample) for k, v in inputs.items()},
        )
        return {
            "before": records(before.head(12)),
            "after": records(after.head(12)),
            "before_columns": list(before.columns),
            "after_columns": list(after.columns),
            "rows_before": len(before),
            "rows_after": len(after),
            "sampled": True,
            "sample_size": len(before),
            "sample_mode": mode,
            "statistics_before": profile(before),
            "statistics_after": profile(after),
            "revision": dataset["revision"],
            "chart": chart,
            "parameters": p,
            "warnings": list(REGISTRY.get(operation).warnings),
            "python": self.python(dataset_id, [{"operation": operation, "parameters": p}]),
        }

    def python(self, dataset_id, steps):
        return self.python_workflow(dataset_id, steps)

    def enqueue(self, dataset_id, steps, revision):
        dataset = self.dataset(dataset_id)
        if revision != dataset["revision"]:
            raise ValueError("Dataset changed. Refresh and preview again.")
        if not 1 <= len(steps) <= 30:
            raise ValueError("A workflow must contain 1 to 30 steps.")
        for step in steps:
            REGISTRY.get(step["operation"])
        steps = self.validate_steps(steps)
        inputs = self.capture_inputs(dataset_id, steps)
        run_id = str(uuid4())
        data = {
            "steps": steps,
            "inputs": inputs,
            "started_at": now(),
            "input_key": dataset["head_key"],
            "revision": revision,
            "input_hash": Path(dataset["head_key"]).name,
            "input_lineage": json.loads(dataset["lineage_json"]),
            "mediasensei_version": __version__,
            "libraries": {
                "pandas": pd.__version__,
                "numpy": np.__version__,
                "pyarrow": pa.__version__,
                "python": platform.python_version(),
            },
        }
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO operation_runs VALUES (?,?,NULL,?,?,?,?)",
                (run_id, dataset_id, "queued", json.dumps(data), now(), now()),
            )
        try:
            job = JobQueue(self.catalog).enqueue(
                project_id=dataset["project_id"],
                kind="operation.workflow",
                processor=ProcessorSpec(
                    id="core.operation", version="1.0.0", deterministic=False, cacheable=False
                ),
                items=[
                    WorkItem(
                        hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                        run_id,
                        0,
                    )
                ],
                parameters={"run_id": run_id},
            )
            with self.catalog.connect() as db:
                db.execute("UPDATE operation_runs SET job_id=? WHERE id=?", (job.id, run_id))
        except Exception as error:
            self._save_run(run_id, "failed", {**data, "error": str(error)})
            raise
        return {"run_id": run_id, "job_id": job.id}

    def _save_run(self, run_id, state, data):
        with self.catalog.connect() as db:
            db.execute(
                "UPDATE operation_runs SET state=?, data_json=?, updated_at=? WHERE id=?",
                (state, json.dumps(data), now(), run_id),
            )

    def run_record(self, run_id):
        with self.catalog.connect() as db:
            row = db.execute("SELECT * FROM operation_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Operation run not found.")
        return {**dict(row), "data": json.loads(row["data_json"])}

    def execute_run(self, run_id):
        run = self.run_record(run_id)
        if run["state"] == "completed":
            return run["data"]
        data = run["data"]
        started = time.monotonic()
        self._save_run(run_id, "running", data)
        try:
            cache_enabled=all(REGISTRY.get(step["operation"]).cacheable and REGISTRY.get(step["operation"]).deterministic for step in data["steps"])
            cache_key = hashlib.sha256(
                json.dumps(
                    {
                        "input": data["input_key"],
                        "steps": data["steps"],
                        "libraries": data["libraries"],
                        "versions": {
                            step["operation"]: REGISTRY.get(step["operation"]).version
                            for step in data["steps"]
                        },
                        "engine": "1.1.0",
                        "inputs": data.get("inputs", {}),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            with self.catalog.connect() as db:
                cached = db.execute(
                    "SELECT result_json FROM operation_cache WHERE cache_key=?", (cache_key,)
                ).fetchone()
            cached = json.loads(cached[0]) if cached and cache_enabled else None
            if cached and "history" in cached and self.store.resolve(cached["key"]).exists():
                key, history, row_count, columns = (
                    cached["key"],
                    cached["history"],
                    cached["rows"],
                    cached["columns"],
                )
                cache_hit = True
            else:
                frame = self.frame(data["input_key"])
                inputs = {k: self.frame(v) for k, v in data.get("inputs", {}).items()}
                history = []
                checkpoints = data.get("checkpoints", [])
                for step_index, step in enumerate(data["steps"]):
                    if (
                        step_index < len(checkpoints)
                        and self.store.resolve(checkpoints[step_index]["key"]).exists()
                    ):
                        frame = self.frame(checkpoints[step_index]["key"])
                        history.append(checkpoints[step_index]["history"])
                        continue
                    definition = REGISTRY.get(step["operation"])
                    frame, chart, p = execute_frame(
                        frame, step["operation"], step.get("parameters", {}), inputs
                    )
                    history.append(
                        {
                            "operation": definition.id,
                            "operation_version": definition.version,
                            "parameters": p,
                            "chart": chart,
                            "rows": len(frame),
                            "warnings": list(definition.warnings),
                        }
                    )
                    with tempfile.TemporaryDirectory(dir=self.store.temp_root) as folder:
                        checkpoint_path = Path(folder) / "step.parquet"
                        frame.to_parquet(checkpoint_path, index=False)
                        checkpoint_key = self.store.import_file(checkpoint_path).object_key
                    checkpoints.append({"key": checkpoint_key, "history": history[-1]})
                    data["checkpoints"] = checkpoints
                    data["progress"] = {
                        "completed_steps": len(history),
                        "total_steps": len(data["steps"]),
                        "processed_count": len(frame),
                        "failed_count": 0,
                        "skipped_count": 0,
                    }
                    self._save_run(run_id, "running", data)
                    current = self.run_record(run_id)
                    if current["job_id"]:
                        JobQueue(self.catalog).log_event(
                            current["job_id"],
                            "info",
                            "operation_step",
                            f"Completed {definition.name} ({len(history)}/{len(data['steps'])})",
                            {"rows": len(frame)},
                        )
                        if JobQueue(self.catalog).get(current["job_id"]).state.value == "cancelled":
                            raise ValueError("Operation cancelled; output was not applied.")
                with tempfile.TemporaryDirectory(dir=self.store.temp_root) as folder:
                    path = Path(folder) / "output.parquet"
                    frame.to_parquet(path, index=False)
                    key = self.store.import_file(path).object_key
                row_count, columns = len(frame), list(frame.columns)
                cache_hit = False
            data.update(
                {
                    "output_key": key,
                    "output_hash": Path(key).name,
                    "history": history,
                    "rows": row_count,
                    "columns": columns,
                    "cache_hit": cache_hit,
                    "runtime_seconds": round(time.monotonic() - started, 3),
                    "finished_at": now(),
                }
            )
            changes = any(s["operation"] not in REPORTS for s in data["steps"])
            current_run = self.run_record(run_id)
            if (
                current_run["job_id"]
                and JobQueue(self.catalog).get(current_run["job_id"]).state.value == "cancelled"
            ):
                raise ValueError("Operation was cancelled; output was not applied.")
            with self.catalog.connect() as db:
                if changes:
                    updated = db.execute(
                        "UPDATE lab_datasets SET head_key=?, revision=revision+1, updated_at=?,lineage_json=? WHERE id=? AND revision=?",
                        (
                            key,
                            now(),
                            json.dumps([*data["input_lineage"], run_id]),
                            run["dataset_id"],
                            data["revision"],
                        ),
                    )
                    if updated.rowcount != 1:
                        raise ValueError(
                            "The working dataset changed during processing. Output was preserved, but not applied. Refresh before retrying."
                        )
                if cache_enabled:
                    db.execute(
                        "INSERT OR REPLACE INTO operation_cache VALUES (?,?)",
                        (
                            cache_key,
                            json.dumps(
                                {"key": key, "history": history, "rows": row_count, "columns": columns}
                            ),
                        ),
                    )
                db.execute(
                    "UPDATE operation_runs SET state=?,data_json=?,updated_at=? WHERE id=?",
                    ("completed", json.dumps(data), now(), run_id),
                )
            return data
        except Exception as error:
            self._save_run(run_id, "failed", {**data, "error": str(error), "finished_at": now()})
            raise

    def runs(self, dataset_id):
        with self.catalog.connect() as db:
            rows = db.execute(
                "SELECT id FROM operation_runs WHERE dataset_id=? ORDER BY created_at DESC LIMIT 100",
                (dataset_id,),
            ).fetchall()
        return [self.run_record(row["id"]) for row in rows]

    def version(self, dataset_id, name):
        dataset = self.dataset(dataset_id)
        manifest = {
            **dataset,
            "mediasensei_version": __version__,
            "profile": self.cached_profile(dataset["head_key"]),
            "runs": [self.run_record(run_id) for run_id in json.loads(dataset["lineage_json"])],
        }
        version_id = str(uuid4())
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO lab_versions VALUES (?,?,?,?,?)",
                (version_id, dataset_id, name, json.dumps(manifest), now()),
            )
        return {"id": version_id, "name": name, "manifest": manifest}

    def versions(self, dataset_id):
        with self.catalog.connect() as db:
            return [
                {**dict(row), "manifest": json.loads(row["manifest_json"])}
                for row in db.execute(
                    "SELECT * FROM lab_versions WHERE dataset_id=? ORDER BY created_at DESC",
                    (dataset_id,),
                )
            ]

    def restore(self, dataset_id, version_id, revision):
        version = next((v for v in self.versions(dataset_id) if v["id"] == version_id), None)
        if not version:
            raise KeyError("Version not found in this dataset.")
        with self.catalog.connect() as db:
            updated = db.execute(
                "UPDATE lab_datasets SET head_key=?,revision=revision+1,updated_at=?,lineage_json=? WHERE id=? AND revision=?",
                (
                    version["manifest"]["head_key"],
                    now(),
                    version["manifest"]["lineage_json"],
                    dataset_id,
                    revision,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("Dataset changed. Refresh before restoring.")
        return self.dataset(dataset_id)

    def save_recipe(self, name, steps, recipe_id=None):
        if not 1 <= len(steps) <= 30:
            raise ValueError("A recipe needs 1 to 30 steps.")
        for step in steps:
            REGISTRY.get(step["operation"])
        self.validate_steps(steps, placeholders=True)
        recipe_id = recipe_id or str(uuid4())
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO lab_recipes VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,steps_json=excluded.steps_json",
                (recipe_id, name, json.dumps(steps), now()),
            )
        return {"id": recipe_id, "name": name, "steps": steps}

    def recipes(self):
        with self.catalog.connect() as db:
            return [
                {**dict(row), "steps": json.loads(row["steps_json"])}
                for row in db.execute("SELECT * FROM lab_recipes ORDER BY created_at DESC")
            ]


def register_operation_processors(registry, catalog):
    workbench = Workbench(catalog)
    registry.register(
        "core.operation", lambda item, parameters: workbench.execute_run(parameters["run_id"])
    )
