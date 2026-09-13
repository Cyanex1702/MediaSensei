"""Persisted workflow, query, visualization and immutable comparison services."""

from __future__ import annotations

import json
import re
from collections import Counter
from uuid import uuid4

import numpy as np
import pandas as pd

from mediasensei.domain.operations import REGISTRY

PLACEHOLDER = re.compile(r"^\{\{([A-Za-z_][A-Za-z_0-9]*)(?::(.*))?\}\}$")


def resolve_parameters(value, bindings):
    if isinstance(value, dict):
        return {k: resolve_parameters(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_parameters(v, bindings) for v in value]
    match = PLACEHOLDER.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return value
    name, default = match.groups()
    if name in bindings:
        return bindings[name]
    if default is not None:
        try:
            return json.loads(default)
        except json.JSONDecodeError:
            return default
    raise ValueError(f"Provide a value for recipe parameter {name}.")


def placeholders(value):
    result = {}

    def visit(v):
        if isinstance(v, dict):
            for item in v.values():
                visit(item)
        elif isinstance(v, list):
            for item in v:
                visit(item)
        elif isinstance(v, str):
            match = PLACEHOLDER.fullmatch(v)
            if match:
                name, default = match.groups()
                try:
                    result[name] = json.loads(default) if default is not None else None
                except json.JSONDecodeError:
                    result[name] = default

    visit(value)
    return result


class WorkflowFeatures:
    @staticmethod
    def migrate_features(db):
        db.executescript("""
        CREATE TABLE IF NOT EXISTS lab_profiles(key TEXT PRIMARY KEY, profile_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lab_queries(id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,query_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lab_charts(id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,name TEXT NOT NULL,definition_json TEXT NOT NULL,data_json TEXT NOT NULL,input_key TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lab_workflows(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,name TEXT NOT NULL,steps_json TEXT NOT NULL,updated_at TEXT NOT NULL);
        """)

    def cached_profile(self, key):
        from mediasensei.operations import profile

        cache_key = "1.1:" + key
        with self.catalog.connect() as db:
            cached = db.execute(
                "SELECT profile_json FROM lab_profiles WHERE key=?", (cache_key,)
            ).fetchone()
        if cached:
            return json.loads(cached[0])
        result = profile(self.frame(key))
        with self.catalog.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO lab_profiles VALUES (?,?)", (cache_key, json.dumps(result))
            )
        return result

    def sample_frame(self, key, size=100, mode="first", seed=42, selected=None):
        if mode == "first":
            return self.frame(key, sample=size)
        # Bounded Arrow batches + reservoir positions; no full table decoding for random previews.
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(self.store.resolve(key))
        count = parquet.metadata.num_rows
        if mode == "selected":
            indices = selected or []
            if (
                not indices
                or len(indices) > 500
                or any(type(i) != int or i < 0 or i >= count for i in indices)
            ):
                raise ValueError("Select 1 to 500 valid row positions.")
            indices = np.array(sorted(set(indices)))
        elif mode in ["random", "representative"]:
            indices = (
                np.sort(np.random.default_rng(seed).choice(count, min(size, count), replace=False))
                if count
                else np.array([], dtype=int)
            )
            if mode == "representative":
                indices = np.unique(np.linspace(0, max(count - 1, 0), min(size, count)).astype(int))
        else:
            raise ValueError("Unknown sampling mode.")
        parts = []
        offset = 0
        for batch in parquet.iter_batches(batch_size=4096):
            wanted = indices[(indices >= offset) & (indices < offset + len(batch))] - offset
            if len(wanted):
                parts.append(batch.take(wanted).to_pandas())
            offset += len(batch)
            if len(indices) and offset > indices[-1]:
                break
        return (
            pd.concat(parts, ignore_index=True)
            if parts
            else parquet.schema_arrow.empty_table().to_pandas()
        )

    def validate_steps(self, steps, placeholders=False):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValueError("Use 1 to 30 operation nodes.")
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Each node must be an operation object.")  # noqa: TRY004
            definition = REGISTRY.get(step.get("operation", ""))
            if definition.modality != "tabular":
                raise ValueError(
                    "This pipeline accepts TabularDataset nodes. Use the matching media lab for asset operations."
                )
            p = step.get("parameters", {})
            if not isinstance(p, dict):
                raise ValueError("Node parameters must be an object.")  # noqa: TRY004
            if set(p) - set(definition.parameter_schema):
                raise ValueError(f"Unknown parameters for {definition.name}.")
            if not placeholders and globals()["placeholders"](p):
                raise ValueError("Bind recipe placeholders before preview or execution.")
        return steps

    def capture_inputs(self, dataset_id, steps):
        result = {}
        project = self.dataset(dataset_id)["project_id"]
        for step in steps:
            if step["operation"] == "combine":
                other = step.get("parameters", {}).get("dataset")
                if not other:
                    raise ValueError("Choose a second dataset for Combine.")
                ds = self.dataset(other)
                if ds["project_id"] != project:
                    raise ValueError("Combine inputs must belong to the same project.")
                result[other] = ds["head_key"]
        return result

    def dry_run(
        self, dataset_id, steps, revision, bindings=None, mode="first", seed=42, selected=None
    ):
        from mediasensei.operations import execute_frame, records

        steps = self.validate_steps(resolve_parameters(steps, bindings or {}))
        dataset = self.dataset(dataset_id)
        if dataset["revision"] != revision:
            raise ValueError("Dataset changed. Refresh before previewing.")
        frame = self.sample_frame(dataset["head_key"], 100, mode, seed, selected)
        before = records(frame.head(12))
        history = []
        inputs = {
            k: self.frame(v, sample=100) for k, v in self.capture_inputs(dataset_id, steps).items()
        }
        for step in steps:
            frame, chart, p = execute_frame(
                frame, step["operation"], step.get("parameters", {}), inputs
            )
            history.append(
                {
                    "name": REGISTRY.get(step["operation"]).name,
                    "rows": len(frame),
                    "columns": len(frame.columns),
                    "chart": chart,
                    "parameters": p,
                    "input_type": "TabularDataset",
                    "output_type": "TabularDataset",
                }
            )
        return {
            "before": before,
            "after": records(frame.head(12)),
            "history": history,
            "sampled": True,
            "steps": steps,
        }

    def python_workflow(self, dataset_id, steps):
        self.validate_steps(steps) if steps else None
        payload = json.dumps(steps, ensure_ascii=True)
        input_ids = sorted(
            {s["parameters"]["dataset"] for s in steps if s["operation"] == "combine"}
        )
        inputs = "\n".join(
            f'inputs[{identifier!r}] = pd.read_parquet("inputs/{identifier}.parquet")'
            for identifier in input_ids
        )
        return (
            "import json\nimport pandas as pd\nfrom mediasensei.operations import execute_frame\n\n"
            "# Use the MediaSensei version recorded in manifest.json.\n"
            'df = pd.read_parquet("input.parquet")\ninputs = {}\n' + inputs + "\n"
            f"steps = json.loads({payload!r})\n"
            'for step in steps:\n    df, report, parameters = execute_frame(df, step["operation"], step["parameters"], inputs)\n'
            'df.to_parquet("output.parquet", index=False)\n'
        )

    def compare_versions(self, dataset_id, left, right="", identity="", target=""):
        from mediasensei.operations import records

        versions = {v["id"]: v["manifest"] for v in self.versions(dataset_id)}
        if left not in versions or (right and right not in versions):
            raise KeyError("Version not found.")
        a = versions[left]
        b = versions[right] if right else self.dataset(dataset_id)
        old = self.frame(a["head_key"])
        new = self.frame(b["head_key"])
        common = [c for c in old if c in new]
        added = []
        removed = []
        changes = []
        if identity:
            if (
                identity not in common
                or old[identity].isna().any()
                or new[identity].isna().any()
                or old[identity].duplicated().any()
                or new[identity].duplicated().any()
            ):
                raise ValueError(
                    "Comparison identity must be a unique, non-missing column in both versions."
                )
            aa = old.set_index(identity)
            bb = new.set_index(identity)
            added = bb.index.difference(aa.index).astype(str).tolist()
            removed = aa.index.difference(bb.index).astype(str).tolist()
            shared = aa.index.intersection(bb.index)
            for c in common:
                if c == identity:
                    continue
                x = aa.loc[shared, c].astype("string").fillna("<null>")
                y = bb.loc[shared, c].astype("string").fillna("<null>")
                mask = x != y
                if mask.any():
                    changes.append(
                        {
                            "column": c,
                            "kind": "label"
                            if c == target
                            else "split"
                            if c == "_split"
                            else "feature",
                            "count": int(mask.sum()),
                            "examples": [
                                {"id": str(i), "before": str(x[i]), "after": str(y[i])}
                                for i in shared[mask][:10]
                            ],
                        }
                    )
        else:
            # Without an identity column, report exact full-row multiset additions/removals.
            aa = Counter(map(tuple, old[common].astype("string").fillna("<null>").values))
            bb = Counter(map(tuple, new[common].astype("string").fillna("<null>").values))
            added = [str(v) for v, n in (bb - aa).items() for _ in range(n)]
            removed = [str(v) for v, n in (aa - bb).items() for _ in range(n)]
        pa = self.cached_profile(a["head_key"])
        pb = self.cached_profile(b["head_key"])
        return {
            "samples_added": len(added),
            "samples_removed": len(removed),
            "added_examples": added[:20],
            "removed_examples": removed[:20],
            "changes": changes,
            "columns_added": [c for c in new if c not in old],
            "columns_removed": [c for c in old if c not in new],
            "quality_before": pa["findings"],
            "quality_after": pb["findings"],
            "transforms_before": json.loads(a["lineage_json"]),
            "transforms_after": json.loads(b["lineage_json"]),
            "before": records(old.head(12)),
            "after": records(new.head(12)),
            "identity": identity
            or "Exact row values; choose an ID column to distinguish edits from additions/removals.",
        }

    def query_rows(self, dataset_id, query):
        import duckdb
        import pyarrow.parquet as pq

        from mediasensei.operations import now, records

        dataset = self.dataset(dataset_id)
        path = self.store.resolve(dataset["head_key"])
        columns = pq.read_schema(path).names

        def col(name):
            if name not in columns:
                raise ValueError("Filter/sort column no longer exists.")
            return '"' + name.replace('"', '""') + '"'

        position = "__sensei_position__"
        while position in columns:
            position += "x"
        search = query.get("search", "")
        conditions = query.get("conditions", [])
        if (
            not isinstance(search, str)
            or len(search) > 1000
            or not isinstance(conditions, list)
            or len(conditions) > 30
        ):
            raise ValueError("Use a short search and at most 30 conditions.")
        clauses = []
        args = []
        if search:
            clauses.append(
                "("
                + " OR ".join("contains(CAST(" + col(c) + " AS VARCHAR), ?)" for c in columns)
                + ")"
            )
            args.extend([search] * len(columns))
        parts = []
        for condition in conditions:
            c = col(condition.get("column"))
            op = condition.get("operator")
            value = condition.get("value")
            if op in ["gt", "ge", "lt", "le"]:
                symbol = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op]
                parts.append(f"CAST({c} AS DOUBLE) {symbol} ?")
                args.append(float(value))
            elif op in ["eq", "ne"]:
                parts.append(f"CAST({c} AS VARCHAR) {'=' if op == 'eq' else '<>'} ?")
                args.append(str(value))
            elif op in ["contains", "regex"]:
                if not isinstance(value, str) or len(value) > 200:
                    raise ValueError("Pattern must be at most 200 characters.")
                parts.append(
                    f"{'contains' if op == 'contains' else 'regexp_matches'}(CAST({c} AS VARCHAR), ?)"
                )
                args.append(value)
            elif op in ["is_null", "not_null"]:
                parts.append(f"{c} IS {'NOT ' if op == 'not_null' else ''}NULL")
            elif op == "in":
                if not isinstance(value, list) or not value or len(value) > 500:
                    raise ValueError("Supply 1–500 category values.")
                parts.append(f"CAST({c} AS VARCHAR) IN (" + ",".join("?" for _ in value) + ")")
                args.extend(map(str, value))
            elif op == "between_dates":
                if not isinstance(value, list) or len(value) != 2:
                    raise ValueError("Date range requires start and end.")
                parts.append(
                    f"CAST({c} AS TIMESTAMPTZ) BETWEEN CAST(? AS TIMESTAMPTZ) AND CAST(? AS TIMESTAMPTZ)"
                )
                args.extend(value)
            else:
                raise ValueError("Unknown filter operator.")
        if parts:
            clauses.append(
                "(" + (" OR " if query.get("match") == "any" else " AND ").join(parts) + ")"
            )
        where = " AND ".join(clauses) or "true"
        sort = query.get("sort_by")
        order = col(sort) if sort else '"' + position + '"'
        offset = query.get("offset", 0)
        limit = query.get("limit", 50)
        if type(offset) != int or offset < 0 or type(limit) != int or not 1 <= limit <= 200:
            raise ValueError("Use a nonnegative offset and 1–200 row page size.")
        source = f'(SELECT row_number() OVER () - 1 AS "{position}", * FROM read_parquet(?))'
        try:
            with duckdb.connect(config={"memory_limit": "256MB", "threads": 2}) as connection:
                count = connection.execute(
                    f"SELECT count(*) FROM {source} WHERE {where}", [str(path), *args]
                ).fetchone()[0]
                frame = connection.execute(
                    f"SELECT * FROM {source} WHERE {where} ORDER BY {order} {'DESC' if query.get('descending') else 'ASC'} NULLS LAST LIMIT ? OFFSET ?",
                    [str(path), *args, limit, offset],
                ).df()
        except duckdb.Error as e:
            raise ValueError(
                "Query failed: check numeric/date types and regular expression syntax. "
                + str(e).splitlines()[0]
            ) from e
        positions = frame.pop(position).tolist()
        if query.get("remember"):
            with self.catalog.connect() as db:
                db.execute(
                    "INSERT INTO lab_queries VALUES (?,?,?,?)",
                    (str(uuid4()), dataset_id, json.dumps(query), now()),
                )
                db.execute(
                    "DELETE FROM lab_queries WHERE dataset_id=? AND id NOT IN (SELECT id FROM lab_queries WHERE dataset_id=? ORDER BY created_at DESC LIMIT 30)",
                    (dataset_id, dataset_id),
                )
        return {
            "rows": records(frame),
            "positions": positions,
            "columns": columns,
            "total": count,
            "revision": dataset["revision"],
        }

    def query_history(self, dataset_id):
        with self.catalog.connect() as db:
            return [
                {**dict(r), "query": json.loads(r["query_json"])}
                for r in db.execute(
                    "SELECT * FROM lab_queries WHERE dataset_id=? ORDER BY created_at DESC",
                    (dataset_id,),
                )
            ]

    def save_workflow(self, project_id, name, steps, identifier=None):
        from mediasensei.operations import now

        self.validate_steps(steps, placeholders=True)
        identifier = identifier or str(uuid4())
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO lab_workflows VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,steps_json=excluded.steps_json,updated_at=excluded.updated_at",
                (identifier, project_id, name, json.dumps(steps), now()),
            )
        return {"id": identifier, "name": name, "steps": steps}

    def workflows(self, project_id):
        with self.catalog.connect() as db:
            return [
                {**dict(r), "steps": json.loads(r["steps_json"])}
                for r in db.execute(
                    "SELECT * FROM lab_workflows WHERE project_id=? ORDER BY updated_at DESC",
                    (project_id,),
                )
            ]

    def save_chart(self, dataset_id, name, definition):
        from mediasensei.operations import execute_frame, now

        dataset = self.dataset(dataset_id)
        operation = definition.get("operation", "chart")
        params = definition.get("parameters", definition)
        _, data, _ = execute_frame(self.frame(dataset["head_key"]), operation, params)
        identifier = str(uuid4())
        if data is None:
            raise ValueError("Choose a report or visualization operation to save.")
        with self.catalog.connect() as db:
            db.execute(
                "INSERT INTO lab_charts VALUES (?,?,?,?,?,?,?)",
                (
                    identifier,
                    dataset_id,
                    name,
                    json.dumps(definition),
                    json.dumps(data),
                    dataset["head_key"],
                    now(),
                ),
            )
        return {"id": identifier, "name": name, "chart": data}

    def charts(self, dataset_id):
        with self.catalog.connect() as db:
            return [
                {
                    **dict(r),
                    "chart": json.loads(r["data_json"]),
                    "definition": json.loads(r["definition_json"]),
                }
                for r in db.execute(
                    "SELECT * FROM lab_charts WHERE dataset_id=? ORDER BY created_at DESC",
                    (dataset_id,),
                )
            ]
