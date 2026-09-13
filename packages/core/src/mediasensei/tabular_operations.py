"""Additional bounded tabular operations; pure functions shared by every interface."""

from __future__ import annotations

import ast
import json
import operator
from statistics import NormalDist

import numpy as np
import pandas as pd


def numeric(frame, columns):
    if any(not pd.api.types.is_numeric_dtype(frame[c]) for c in columns):
        raise ValueError("Choose numeric columns for this operation.")
    return frame[columns].astype(float)


def column_name(frame, name):
    if not name.strip() or name in frame:
        raise ValueError("Choose a non-empty new column name.")


def expression(frame, source):
    """Small arithmetic AST, never eval/exec, attribute access, calls or subscriptions."""
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
    }
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        raise ValueError("Invalid arithmetic expression.") from e
    if len(list(ast.walk(tree))) > 80:
        raise ValueError("Expression is too complex.")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in frame:
            return numeric(frame, [node.id])[node.id]
        if (
            isinstance(node, ast.Constant)
            and type(node.value) in (float, int)
            and abs(node.value) < 1e100
        ):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
        raise ValueError("Use column identifiers, numbers, parentheses and + - * / %.")

    try:
        return visit(tree)
    except (ZeroDivisionError, OverflowError) as e:
        raise ValueError("Invalid arithmetic: division by zero or overflow.") from e


def condition_mask(frame, conditions, match="all"):
    if not isinstance(conditions, list) or len(conditions) > 30:
        raise ValueError("Supply at most 30 conditions.")
    mask = pd.Series(match == "all", index=frame.index)
    for c in conditions:
        if not isinstance(c, dict) or c.get("column") not in frame:
            raise ValueError("Each condition needs a valid column.")
        s = frame[c["column"]]
        op = c.get("operator")
        v = c.get("value")
        if op in ["gt", "ge", "lt", "le"]:
            n = pd.to_numeric(s, errors="raise")
            m = getattr(n, op)(float(v))
        elif op in ["eq", "ne"]:
            m = getattr(s.astype("string"), op)(str(v))
        elif op == "in":
            if not isinstance(v, list):
                raise ValueError("Category inclusion needs a list.")
            m = s.isin(v)
        elif op == "between_dates":
            if not isinstance(v, list) or len(v) != 2:
                raise ValueError("Date range needs start and end.")
            m = pd.to_datetime(s, utc=True, errors="raise").between(
                pd.Timestamp(v[0], tz="UTC"), pd.Timestamp(v[1], tz="UTC")
            )
        elif op in ["contains", "regex"]:
            if not isinstance(v, str) or len(v) > 200:
                raise ValueError("Text patterns must be at most 200 characters.")
            if op == "regex":
                import pyarrow as pa
                import pyarrow.compute as pc

                try:
                    m = pd.Series(
                        pc.fill_null(
                            pc.match_substring_regex(pa.array(s.astype("string")), v), False
                        ).to_numpy(),
                        index=s.index,
                    )
                except pa.ArrowInvalid as e:
                    raise ValueError(f"Invalid RE2 regular expression: {e}") from e
            else:
                m = s.astype("string").str.contains(v, regex=False, na=False)
        elif op == "is_null":
            m = s.isna()
        elif op == "not_null":
            m = s.notna()
        else:
            raise ValueError("Unknown filter operator.")
        mask = (mask & m.fillna(False)) if match == "all" else (mask | m.fillna(False))
    return mask


def run_extra(frame, operation, p, inputs=None):
    from mediasensei.operations import profile, records

    out = frame.copy(deep=True)
    report = None

    def table(title, data):
        return {"kind": "table", "title": title, "values": records(data)}

    if operation == "statistics":
        df = out[p["columns"]]
        method = p["method"]
        if method == "describe":
            data = df.describe(include="all").reset_index()
        elif method == "covariance":
            data = numeric(df, list(df)).cov().reset_index()
        elif method == "quantiles":
            data = numeric(df, list(df)).quantile([0, 0.01, 0.25, 0.5, 0.75, 0.99, 1]).reset_index()
        elif method == "memory":
            data = pd.DataFrame(
                {"column": list(df), "bytes": df.memory_usage(deep=True, index=False).values}
            )
        else:
            parts = []
            for c in df:
                counts = df[c].astype("string").value_counts(dropna=False).head(500)
                parts.extend(
                    {"column": c, "value": str(k), "count": int(n)} for k, n in counts.items()
                )
            data = pd.DataFrame(parts)
            if method == "unique":
                data = data.drop(columns="count")
        report = table(method, data)
    elif operation == "duplicates":
        for c in ["_duplicate_group", "_canonical"]:
            if c in out:
                raise ValueError(f"{c} already exists; rename it first.")
        out["_duplicate_group"] = out.groupby(p["columns"], dropna=False, sort=False).ngroup()
        out["_canonical"] = ~out.duplicated(subset=p["columns"], keep=p["keep"])
    elif operation == "exclude":
        if not isinstance(p["rows"], list) or any(
            type(i) != int or i < 0 or i >= len(out) for i in p["rows"]
        ):
            raise ValueError("Selected row positions are outside the current dataset.")
        out = out.drop(out.index[p["rows"]])
    elif operation == "conditions":
        out = out.loc[condition_mask(out, p["conditions"], p["match"])]
    elif operation == "derive":
        column_name(out, p["name"])
        out[p["name"]] = expression(out, p["expression"])
    elif operation == "strings":
        s = out[p["column"]].astype("string")
        m = p["method"]
        if m in ["strip", "upper", "lower", "length"]:
            out[p["column"]] = getattr(s.str, "len" if m == "length" else m)()
        elif m == "replace":
            out[p["column"]] = s.str.replace(p["value"], p["replacement"], regex=False)
        else:
            if not p["value"]:
                raise ValueError("Delimiter cannot be empty.")
            out[p["column"]] = s.str.split(p["value"], regex=False).str.get(int(p["index"]))
    elif operation == "dates":
        column_name(out, p["name"])
        s = pd.to_datetime(out[p["column"]], utc=True, errors="raise")
        m = p["method"]
        out[p["name"]] = (
            s.dt.floor("D")
            if m == "floor_day"
            else s.dt.strftime("%Y-%m-01")
            if m == "floor_month"
            else getattr(s.dt, m)
        )
    elif operation == "replace":
        if not isinstance(p["mapping"], dict):
            raise ValueError("Mapping must be an object of old/new values.")
        s = out[p["column"]]
        mapping = p["mapping"]
        out[p["column"]] = s.map(lambda v: mapping.get(str(v), v))
    elif operation == "aggregate":
        if p["method"] not in ["count", "nunique"]:
            numeric(out, p["columns"])
        values = [c for c in p["columns"] if c not in p["by"]]
        if not values:
            raise ValueError("Choose value columns distinct from group columns.")
        out = out.groupby(p["by"], dropna=False, as_index=False)[values].agg(p["method"])
    elif operation == "pivot":
        if out[p["column"]].nunique() > 500:
            raise ValueError("Pivot is limited to 500 output categories.")
        out = out.pivot_table(
            index=p["index"],
            columns=p["column"],
            values=p["value"],
            aggfunc=p["method"],
            dropna=False,
        ).reset_index()
        out.columns = out.columns.map(str)
    elif operation == "melt":
        if len(out) * (len(out.columns) - len(p["columns"])) > 200000:
            raise ValueError("Melt would exceed 200,000 rows.")
        out = out.melt(id_vars=p["columns"])
        out["value"] = out["value"].astype("string")
    elif operation == "explode":
        if not p["separator"]:
            raise ValueError("Separator cannot be empty.")
        s = out[p["column"]].astype("string").str.split(p["separator"], regex=False)
        if s.str.len().sum() > 200000:
            raise ValueError("Explode would exceed 200,000 rows.")
        out[p["column"]] = s
        out = out.explode(p["column"])
    elif operation == "combine":
        other = (inputs or {}).get(p["dataset"])
        if other is None:
            raise ValueError("A second dataset snapshot is required.")
        method = p["method"]
        if method == "concat":
            if len(out) + len(other) > 200000:
                raise ValueError("Concatenation exceeds 200,000 rows.")
            out = pd.concat([out, other], ignore_index=True)
        else:
            if p["left_on"] not in out or p["right_on"] not in other:
                raise ValueError("Select valid left and right join keys.")
            left = out.groupby(p["left_on"], dropna=False).size()
            right = other.groupby(p["right_on"], dropna=False).size()
            estimate = (
                left.to_frame("l")
                .join(right.to_frame("r"), how="outer")
                .fillna(1)
                .prod(axis=1)
                .sum()
            )
            if estimate > 200000:
                raise ValueError("Join would exceed 200,000 rows; refine keys or aggregate first.")
            out = out.merge(
                other,
                how="left" if method == "lookup" else method,
                left_on=p["left_on"],
                right_on=p["right_on"],
                validate="many_to_one" if method == "lookup" else p["validate"],
                suffixes=("", "_right"),
            )
    elif operation == "ordinal":
        column_name(out, p["name"])
        cats = p["categories"]
        if (
            not isinstance(cats, list)
            or not cats
            or len(cats) > 500
            or len(set(map(str, cats))) != len(cats)
        ):
            raise ValueError("Supply a distinct ordered category list, up to 500 entries.")
        mapping = {str(v): i for i, v in enumerate(cats)}
        s = out[p["column"]]
        out[p["name"]] = s.astype("string").map(mapping).fillna(-1).where(s.notna())
    elif operation == "log":
        values = numeric(out, p["columns"])
        if (values <= -1).any().any():
            raise ValueError("log1p requires values greater than -1.")
        out[p["columns"]] = np.log1p(values)
    elif operation == "outliers":
        data = []
        for c in p["columns"]:
            s = numeric(out, [c])[c].replace([np.inf, -np.inf], np.nan)
            q1, q3 = s.quantile([0.25, 0.75])
            sd = s.std(ddof=0)
            count = (
                int(((s < q1 - 1.5 * (q3 - q1)) | (s > q3 + 1.5 * (q3 - q1))).sum())
                if p["method"] == "iqr"
                else int(((s - s.mean()).abs() / (sd or 1) > p["threshold"]).sum())
            )
            data.append(
                {
                    "column": c,
                    "outliers": count,
                    "variance": float(s.var(ddof=0)),
                    "low_variance": bool(s.var(ddof=0) <= p["threshold"]),
                }
            )
        report = table("Outliers and variance", pd.DataFrame(data))
    elif operation == "quality":
        findings = profile(out)["findings"]
        target = p["target"]
        group = p["group"]
        if target:
            counts = out[target].value_counts(dropna=False)
            findings.append(
                {
                    "title": f"{target}: class proportions",
                    "reason": "; ".join(
                        f"{k}: {n} ({n / max(len(out), 1):.1%})" for k, n in counts.head(30).items()
                    ),
                    "operation": "split",
                    "parameters": {"strategy": "stratified", "column": target},
                }
            )
            for c in out:
                if c != target and out[c].astype("string").equals(out[target].astype("string")):
                    findings.append(
                        {
                            "title": f"{c} copies target {target}",
                            "reason": "Remove target-derived predictors to prevent leakage.",
                            "operation": "drop_columns",
                            "parameters": {"columns": [c]},
                        }
                    )
        if group and "_split" in out:
            overlaps = int(out.groupby(group, dropna=False)["_split"].nunique().gt(1).sum())
            findings.append(
                {
                    "title": f"{overlaps} groups cross splits",
                    "reason": "Use group-aware splitting when samples share a source.",
                    "operation": "split",
                    "parameters": {"strategy": "group", "column": group},
                }
            )
        report = {
            "kind": "table",
            "title": "Quality findings",
            "values": [{"finding": f["title"], "reason": f["reason"]} for f in findings],
        }
    elif operation == "preprocess":
        out, fitted = fit_training(out, p)
        report = {
            "kind": "table",
            "title": "Training-only fitted parameters",
            "values": [{"feature": k, "fitted": json.dumps(v)} for k, v in fitted.items()],
            "fitted": fitted,
        }
    elif operation == "chart":
        report = chart_data(out, p)
    else:
        raise ValueError(f"Unknown operation: {operation}")
    if len(out) > 200000 or len(out.columns) > 1000:
        raise ValueError("Result exceeds the 200,000 row / 1,000 column working limit.")
    if out.columns.duplicated().any():
        raise ValueError("Result has duplicate column names; rename conflicting columns first.")
    return out, report


def fit_training(out, p):
    if "_split" not in out or not (out["_split"] == "train").any():
        raise ValueError("Create a split with training rows before fitting preprocessing.")
    numeric_cols = p["numeric"]
    categorical = p["categorical"]
    if (
        not isinstance(numeric_cols, list)
        or not isinstance(categorical, list)
        or not numeric_cols + categorical
    ):
        raise ValueError("Select numeric and/or categorical features.")
    cols = numeric_cols + categorical
    if (
        len(set(cols)) != len(cols)
        or any(c not in out for c in cols)
        or "_split" in cols
        or p["target"] in cols
    ):
        raise ValueError("Choose distinct existing features and exclude target/split columns.")
    fitted = {}
    train = out.loc[out["_split"] == "train"]
    for c in numeric_cols:
        values = numeric(out, [c])[c]
        t = numeric(train, [c])[c]
        median = t.median()
        if not np.isfinite(median):
            raise ValueError(f"{c} has no finite training values.")
        t = t.fillna(median)
        values = values.fillna(median)
        method = p["method"]
        center = t.mean() if method == "standard" else t.min() if method == "minmax" else t.median()
        width = (
            t.std(ddof=0)
            if method == "standard"
            else t.max() - t.min()
            if method == "minmax"
            else t.quantile(0.75) - t.quantile(0.25)
        )
        width = width or 1
        out[c] = (values - center) / width
        fitted[c] = {
            "median": float(median),
            "center": float(center),
            "width": float(width),
            "method": method,
        }
    for c in categorical:
        cats = sorted(train[c].dropna().astype(str).unique())
        if len(cats) > 100:
            raise ValueError("Training vocabulary is limited to 100 categories per feature.")
        s = out[c].astype("string")
        fitted[c] = {"categories": cats, "unknown": "all zero", "missing": "explicit indicator"}
        for i, cat in enumerate(cats):
            name = f"{c}__{i}"
            column_name(out, name)
            out[name] = s.eq(cat).fillna(False).astype(int)
        name = f"{c}__missing"
        column_name(out, name)
        out[name] = s.isna().astype(int)
        out = out.drop(columns=c)
    return out, fitted


def chart_data(frame, p):
    from mediasensei.operations import records

    kind = p["kind"]
    x = p["x"]
    y = p["y"]
    group = p["group"]
    bins = int(p["window"])
    result = {
        "kind": kind,
        "title": f"{kind.title()} · {x or 'dataset'}",
        "values": [],
        "x": x,
        "y": y,
    }
    if kind == "missingness":
        cols = list(frame.columns[:60])
        result.update(
            columns=cols,
            values=[
                {c: int(pd.isna(v)) for c, v in row.items()}
                for row in records(frame[cols].head(100))
            ],
        )
        return result
    if kind == "split":
        x = "_split"
    if x not in frame:
        raise ValueError("Select an X/category column.")
    s = frame[x]
    if kind in ["histogram", "density", "box", "violin", "qq", "outlier", "error"]:
        values = (
            pd.to_numeric(s, errors="raise").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        )
        if len(values) < 2:
            raise ValueError("This chart needs at least two finite values.")
        counts, edges = np.histogram(values, bins=bins)
        if kind == "histogram":
            result["values"] = [
                {"name": f"{edges[i]:.3g}–{edges[i + 1]:.3g}", "value": int(n)}
                for i, n in enumerate(counts)
            ]
        elif kind in ["density", "violin"]:
            # Binned Gaussian kernel density keeps memory bounded by bins, not row count.
            centers = (edges[:-1] + edges[1:]) / 2
            bw = max(float(np.std(values)) * len(values) ** (-0.2), 1e-9)
            grid = np.linspace(values.min() - bw, values.max() + bw, 100)
            density = (
                np.exp(-0.5 * ((grid[:, None] - centers[None, :]) / bw) ** 2)
                @ counts
                / (len(values) * bw * np.sqrt(2 * np.pi))
            )
            result["values"] = [
                {"x": float(a), "value": float(b)} for a, b in zip(grid, density, strict=True)
            ]
        elif kind == "box":
            result["values"] = [
                dict(
                    zip(
                        ["min", "q1", "median", "q3", "max"],
                        map(float, np.quantile(values, [0, 0.25, 0.5, 0.75, 1])),
                        strict=True,
                    )
                )
            ]
        elif kind == "qq":
            probs = (np.arange(min(len(values), 200)) + 0.5) / min(len(values), 200)
            result["values"] = [
                {"x": NormalDist().inv_cdf(float(a)), "y": float(b)}
                for a, b in zip(probs, np.quantile(values, probs), strict=True)
            ]
        elif kind == "error":
            mean = float(np.mean(values))
            error = 1.96 * float(np.std(values, ddof=1)) / np.sqrt(len(values))
            result["values"] = [{"name": x, "value": mean, "error": error}]
            result["title"] = "Mean with approximate 95% confidence interval"
        else:
            q1, q3 = np.quantile(values, [0.25, 0.75])
            sample = values[:1000]
            result["values"] = [
                {
                    "x": i,
                    "y": float(v),
                    "outlier": bool(v < q1 - 1.5 * (q3 - q1) or v > q3 + 1.5 * (q3 - q1)),
                }
                for i, v in enumerate(sample)
            ]
    elif kind in ["scatter", "bubble", "pair"]:
        cols = (
            [c for c in frame.select_dtypes("number") if c != "_split"][:6]
            if kind == "pair"
            else [x, y] + ([group] if group else [])
        )
        if any(c not in frame for c in cols):
            raise ValueError("Select X and Y numeric columns.")
        numeric(frame, cols)
        result["columns"] = cols
        result["values"] = records(frame[cols].head(1000))
        result["group"] = group
    elif kind in ["line", "rolling"]:
        if y not in frame:
            raise ValueError("Select a numeric Y column.")
        data = frame[[x, y]].copy()
        data[y] = pd.to_numeric(data[y], errors="raise")
        data = data.sort_values(x)
        if kind == "rolling":
            data[y] = data[y].rolling(bins, min_periods=1).mean()
        # Keep evenly spaced points across the entire extent.
        data = data.iloc[
            np.unique(np.linspace(0, max(len(data) - 1, 0), min(len(data), 2000)).astype(int))
        ]
        result["values"] = [
            {"name": str(a), "value": b} for a, b in zip(data[x], data[y], strict=True)
        ]
    else:
        keys = [x] + ([group] if group and kind in ["grouped", "stacked"] else [])
        if p["aggregation"] == "count":
            data = frame.groupby(keys, dropna=False).size().rename("value").reset_index()
        else:
            if y not in frame:
                raise ValueError("Select a numeric Y column for aggregation.")
            numeric(frame, [y])
            data = (
                frame.groupby(keys, dropna=False)[y]
                .agg(p["aggregation"])
                .rename("value")
                .reset_index()
            )
        if len(keys) == 2:
            data = data.pivot(index=x, columns=group, values="value").fillna(0).head(100)
            data.columns = data.columns.map(str)
            result["series"] = list(data.columns[:20])
            data = data[result["series"]].reset_index().rename(columns={x: "name"})
        else:
            data = data.rename(columns={x: "name"}).head(100)
        result["values"] = records(data)
    return result
