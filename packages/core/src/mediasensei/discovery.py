"""Search installed public library APIs and local workspace records without executing user code."""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
from functools import lru_cache

from mediasensei.domain.operations import REGISTRY

GUIDES = [
    (
        "getting-started",
        "Getting started",
        "Import a table, inspect quality, preview transformations, create a version and export a reproducibility bundle.",
    ),
    (
        "cleaning",
        "Data cleaning",
        "Inspect nulls, duplicates and category frequencies first. Decide what missing values mean before imputing. Keep an immutable version before exclusions.",
    ),
    (
        "visualization",
        "Visualization and statistics",
        "Use histograms for distributions, scatter plots for numeric relationships and bars for categories. Correlation does not establish causation. Samples and binned density estimates are labeled.",
    ),
    (
        "ml-preparation",
        "ML preparation without leakage",
        "Remove duplicate samples, split by class or source, then fit preprocessing on training rows only. Protect target and ID columns. Unknown categories use all-zero indicators.",
    ),
    (
        "workflows",
        "Recipes and reproducibility",
        "Nodes pass typed table outputs in order. Combine snapshots its second input. Save a workflow for a project or a parameterized recipe for reuse. Bind {{target}} and {{seed:42}} before running.",
    ),
    (
        "troubleshooting",
        "Troubleshooting operations",
        "Check numeric types, available memory, compatible join keys and current dataset revision. Retry failed jobs to reuse successful checkpoints. Review worker events for the failing node.",
    ),
    (
        "images",
        "Image processing concepts",
        "Image inspection, transforms and OCR run in existing workers. Inspect imported image metadata and select assets in Library before opening Image Lab.",
    ),
    (
        "media",
        "Video and audio concepts",
        "Media inspection and derivatives require FFmpeg and ffprobe. Use the existing Video or Audio Lab to inspect the toolchain and job errors.",
    ),
    (
        "knowledge",
        "Documents and RAG preparation",
        "Document indexing retains source references for retrieval. Inspect extracted text and search results; chunk quality determines retrieval quality.",
    ),
]


@lru_cache(maxsize=1)
def library_functions():
    roots = [
        ("pandas", "DataFrame", "https://pandas.pydata.org/docs/reference/api/"),
        ("numpy", "", "https://numpy.org/doc/stable/reference/generated/"),
        ("sklearn.preprocessing", "", "https://scikit-learn.org/stable/modules/generated/"),
        ("sklearn.model_selection", "", "https://scikit-learn.org/stable/modules/generated/"),
        ("scipy.stats", "", "https://docs.scipy.org/doc/scipy/reference/generated/"),
        ("pyarrow", "", "https://arrow.apache.org/docs/python/generated/"),
    ]
    result = []
    for module_name, attribute, url in roots:
        try:
            module = importlib.import_module(module_name)
            root = getattr(module, attribute) if attribute else module
            package = (
                "scikit-learn" if module_name.startswith("sklearn") else module_name.split(".")[0]
            )
            version = importlib.metadata.version(package)
        except ImportError:
            continue
        for name in dir(root):
            if name.startswith("_"):
                continue
            try:
                obj = inspect.getattr_static(root, name)
            except AttributeError:
                continue
            if not callable(obj):
                continue
            full = f"{module_name}.{attribute + '.' if attribute else ''}{name}"
            doc = inspect.getdoc(obj) or ""
            try:
                signature = str(inspect.signature(obj))[:1200]
            except (ValueError, TypeError):
                signature = "See installed documentation for signature."
            visual = {
                "groupby": "aggregate",
                "pivot_table": "pivot",
                "melt": "melt",
                "explode": "explode",
                "merge": "combine",
                "join": "combine",
                "corr": "correlation",
                "drop_duplicates": "drop_duplicates",
                "fillna": "fill_missing",
                "StandardScaler": "scale",
                "MinMaxScaler": "scale",
                "RobustScaler": "scale",
                "train_test_split": "split",
                "get_dummies": "encode",
            }.get(name)
            result.append(
                {
                    "operation": visual,
                    "id": full,
                    "kind": "Library function",
                    "name": full,
                    "description": doc[:700],
                    "signature": signature,
                    "library": package,
                    "version": version,
                    "url": url + full + ".html",
                }
            )
    return result


def search_functions(query):
    aliases = {
        "heat map": "correlation corr",
        "standard scaler": "StandardScaler",
        "train test split": "train_test_split",
        "rolling average": "rolling",
        "group by": "groupby",
    }
    q = query.lower()
    terms = (q + " " + aliases.get(q, "")).split()
    if not terms:
        return library_functions()[:50]
    results = []
    for r in library_functions():
        text = (r["name"] + " " + r["description"]).lower()
        score = sum(3 * (w in r["name"].lower()) + (w in text) for w in terms)
        if score:
            results.append((score, r))
    return [r for _, r in sorted(results, key=lambda x: -x[0])[:60]]


def search_workspace(service, query, project_id=""):
    terms = set(query.lower().split()) - {"make", "show", "me", "the", "a", "data", "for"}
    result = []
    for op in REGISTRY.search(query):
        result.append(
            {
                "id": op.id,
                "kind": "Operation",
                "name": op.name,
                "description": op.description,
                "operation": op.id,
                "view": "Data Lab"
                if op.modality == "tabular"
                else "Image Lab"
                if op.modality == "image"
                else "Knowledge Lab"
                if op.modality == "document"
                else "Library" if op.modality == "table" else "Video Lab",
            }
        )
    for identifier, title, content in GUIDES:
        if not terms or any(w in (title + " " + content).lower() for w in terms):
            result.append(
                {
                    "id": identifier,
                    "kind": "Guide",
                    "name": title,
                    "description": content,
                    "view": "Documentation",
                }
            )
    with service.catalog.connect() as db:
        queries = [
            ("Project", "SELECT id,name,id AS project_id FROM projects", "Overview"),
            ("Dataset", "SELECT id,name,project_id FROM lab_datasets", "Data Lab"),
            ("Asset", "SELECT id,original_filename AS name,project_id FROM assets", "Library"),
            ("Job", "SELECT id,kind AS name,project_id,state FROM jobs", "Jobs"),
            ("Recipe", "SELECT id,name FROM lab_recipes", "Workflows"),
        ]
        for kind, sql, view in queries:
            # Fetch a bounded set per entity and filter in SQL, not full catalog/browser loads.
            sql += (
                " WHERE "
                + (
                    " AND ".join(
                        "name LIKE ?"
                        if kind not in ["Asset", "Job"]
                        else ("original_filename LIKE ?" if kind == "Asset" else "kind LIKE ?")
                        for _ in terms
                    )
                    if terms
                    else "1=1"
                )
                + " LIMIT 50"
            )
            for row in db.execute(sql, tuple("%" + w + "%" for w in terms)):
                r = dict(row)
                result.append(
                    {
                        "id": r["id"],
                        "kind": kind,
                        "name": r["name"],
                        "description": r.get("state", kind + " in local workspace"),
                        "view": view,
                        "project_id": r.get("project_id"),
                        "dataset_id": r["id"] if kind == "Dataset" else None,
                    }
                )
    with service.catalog.connect() as db:
        for row in db.execute("SELECT DISTINCT model_id,model_revision FROM document_indexes LIMIT 50"):
            if not terms or any(w in row["model_id"].lower() for w in terms):
                result.append({"id":row["model_id"],"kind":"Model","name":row["model_id"],"description":"Installed document index revision "+row["model_revision"],"view":"Knowledge Lab"})
    if any(w in query.lower() for w in ["find","get","acquire","download"]) and any(w in query.lower() for w in ["image","photo","picture"]):
        result.insert(0,{"id":"acquisition","kind":"Navigation","name":"Plan image acquisition","description":"Open Sources to review the acquisition plan before any download.","view":"Sources"})
    for setting in ["Theme colors", "Plugins", "Runtime settings", "Capabilities"]:
        if not terms or any(w in setting.lower() for w in terms):
            result.append({"id":setting,"kind":"Setting","name":setting,"description":"Inspect local settings and capabilities. Theme selection is in the top bar.","view":"System"})
    if query.strip():
        result.extend(search_functions(query)[:8])
    return result[:100]
