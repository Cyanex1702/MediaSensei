"""Discoverable, versioned operation contracts shared by UI, API, SDK and workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationDefinition:
    id: str
    name: str
    category: str
    description: str
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    version: str = "1.1.0"
    modality: str = "tabular"
    backend: str = "pandas + NumPy"
    deterministic: bool = True
    cacheable: bool = True
    preview_supported: bool = True
    batch_supported: bool = True
    warnings: tuple[str, ...] = ()
    plugin_id: str | None = None
    input_types: tuple[str, ...] = ("TabularDataset",)
    output_types: tuple[str, ...] = ("TabularDataset", "Report")
    implementation_reference: str = "mediasensei.operations.execute_frame"

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "input_types": list(self.input_types),
            "output_types": list(self.output_types),
            "beginner_description": self.description,
            "expert_description": f"{self.backend}; operation version {self.version}; deterministic={self.deterministic}. Raw inputs remain immutable.",
            "implementation_reference": self.implementation_reference,
            "documentation_reference": f"operation:{self.id}",
            "resource_requirements": {"max_rows": 200000, "max_parquet_bytes": 268435456},
            "recommendations": [],
            "examples": [
                {
                    "operation": self.id,
                    "parameters": {
                        k: v.get(
                            "default",
                            "<choose column>"
                            if v["type"] == "column"
                            else ["<choose columns>"]
                            if v["type"] == "columns"
                            else "<choose dataset>",
                        )
                        for k, v in self.parameter_schema.items()
                    },
                }
            ],
            "compatibility": {
                "input_types": list(self.input_types),
                "modality": self.modality,
                "requires_columns": [
                    k
                    for k, v in self.parameter_schema.items()
                    if v["type"] in ["column", "columns"]
                ],
            },
            "documentation": {
                "when_to_use": self.description,
                "when_not_to_use": "Do not apply to incompatible input types or fit feature statistics on validation/test data. Inspect a preview and resource limits first.",
                "common_mistakes": list(self.warnings)
                or [
                    "Choosing the wrong column type; relying on a small preview to represent rare categories; running against a stale working revision."
                ],
                "related_operations": [
                    o.id
                    for o in REGISTRY.search(category=self.category, modality=self.modality)
                    if o.id != self.id
                ][:5],
                "equivalent_python": "Configure inputs, then use Preview → Show equivalent Python or Workflow → Show equivalent Python for an exact executable script.",
            },
            "availability": "available",
        }


def param(label: str, kind: str = "columns", **extra) -> dict:
    return {"title": label, "type": kind, **extra}


class OperationRegistry:
    def __init__(self):
        self._operations: dict[str, OperationDefinition] = {}
        self._executors = {}

    def register(self, operation: OperationDefinition, executor=None):
        if operation.id in self._operations:
            raise ValueError(f"Operation already registered: {operation.id}")
        self._operations[operation.id] = operation
        if executor is not None:
            if not callable(executor):
                raise ValueError("Operation executor must be callable.")
            self._executors[operation.id] = executor

    def get(self, operation_id: str) -> OperationDefinition:
        if operation_id not in self._operations:
            raise ValueError(f"Unknown operation: {operation_id}")
        return self._operations[operation_id]

    def search(
        self, query: str = "", category: str = "", modality: str = ""
    ) -> list[OperationDefinition]:
        words = set(query.lower().split()) - {"make", "show", "me", "my", "the", "a", "data", "for"}
        ranked = []
        for op in self._operations.values():
            haystack = f"{op.name} {op.id} {op.description} {' '.join(op.aliases)}".lower()
            score = sum(word in haystack for word in words)
            if (
                (not words or score)
                and (not category or op.category == category)
                and (not modality or op.modality == modality)
            ):
                ranked.append((score, op))
        return [op for _, op in sorted(ranked, key=lambda pair: (-pair[0], pair[1].name))]


REGISTRY = OperationRegistry()


def register(identifier, name, category, description, schema=None, aliases=(), warnings=()):
    REGISTRY.register(
        OperationDefinition(
            identifier, name, category, description, schema or {}, aliases, warnings=warnings
        )
    )


register(
    "profile",
    "Dataset profile",
    "Explore",
    "Inspect missing values, types, statistics and potential quality issues.",
    aliases=("what should I do first", "schema", "statistics", "quality"),
)
register(
    "missing",
    "Missing values report",
    "Explore",
    "Count missing values per column. Missing values can affect downstream training.",
    aliases=("show missing data", "nulls", "missing heat map"),
)
register(
    "correlation",
    "Correlation heatmap",
    "Visualize",
    "Compare numeric relationships. Correlation does not prove causation.",
    aliases=("heat map", "feature correlation", "relationships"),
)
register(
    "distribution",
    "Column distribution",
    "Visualize",
    "Inspect a numeric histogram or category frequencies.",
    {"column": param("Column", "column")},
    ("class distribution", "class imbalance", "histogram", "frequency", "value counts"),
)
register(
    "fill_missing",
    "Fill missing values",
    "Clean",
    "Replace missing values in selected columns. Fit preprocessing on training data to avoid leakage.",
    {
        "columns": param("Columns"),
        "strategy": param(
            "Strategy",
            "enum",
            choices=["median", "mean", "mode", "constant", "forward", "backward"],
            default="median",
        ),
        "value": param("Constant value", "string", default=""),
    },
    ("impute", "fill nulls"),
    ("Do not calculate training statistics using validation/test rows.",),
)
register(
    "drop_missing",
    "Drop missing rows",
    "Clean",
    "Exclude rows missing a value in selected columns, keeping the imported source intact.",
    {"columns": param("Columns")},
)
register(
    "drop_duplicates",
    "Remove duplicate rows",
    "Clean",
    "Keep the first occurrence of each duplicate group using the selected columns.",
    {"columns": param("Match columns")},
    ("deduplicate", "drop duplicates"),
)
register(
    "drop_columns",
    "Drop columns",
    "Transform",
    "Remove selected columns from the working copy.",
    {"columns": param("Columns")},
)
register(
    "scale",
    "Scale numeric features",
    "Features",
    "Scale selected numeric features. Nulls remain null; constant columns become zero.",
    {
        "columns": param("Numeric features"),
        "method": param(
            "Method", "enum", choices=["standard", "minmax", "robust"], default="standard"
        ),
    },
    ("normalize", "standard scaler", "standardize"),
    ("Fit preprocessing on the training partition only for unbiased evaluation.",),
)
register(
    "encode",
    "One-hot encode categories",
    "Features",
    "Create indicator columns for selected categories. Limited to 100 categories per column.",
    {"columns": param("Category columns")},
    ("one hot", "categorical", "encoding"),
)
register(
    "filter",
    "Filter rows",
    "Transform",
    "Keep rows matching a condition. Text matching treats input literally.",
    {
        "column": param("Column", "column"),
        "operator": param(
            "Condition",
            "enum",
            choices=["equals", "not_equal", "greater", "less", "contains", "is_null", "not_null"],
            default="equals",
        ),
        "value": param("Value", "string", default=""),
    },
)
register(
    "sort",
    "Sort rows",
    "Transform",
    "Order rows by a column; missing values appear last.",
    {
        "column": param("Column", "column"),
        "descending": param("Descending", "boolean", default=False),
    },
)
register(
    "rename",
    "Rename a column",
    "Transform",
    "Give one column a new unique name.",
    {"column": param("Column", "column"), "name": param("New name", "string", default="renamed")},
)
register(
    "cast",
    "Convert column type",
    "Transform",
    "Convert values strictly; incompatible values produce an error without changing the dataset.",
    {
        "column": param("Column", "column"),
        "dtype": param("Type", "enum", choices=["string", "number", "datetime"], default="number"),
    },
)
register(
    "clip",
    "Clip numeric outliers",
    "Clean",
    "Bound numeric values by selected quantiles. Review the preview before applying.",
    {
        "columns": param("Numeric columns"),
        "lower": param("Lower quantile", "number", default=0.01, minimum=0, maximum=0.49),
        "upper": param("Upper quantile", "number", default=0.99, minimum=0.51, maximum=1),
    },
)
register(
    "split",
    "Train / validation / test split",
    "ML Preparation",
    "Assign deterministic split labels. Stratify to preserve class proportions where class sizes permit.",
    {
        "strategy": param(
            "Strategy",
            "enum",
            choices=["random", "stratified", "group", "source"],
            default="random",
        ),
        "column": param("Class or group column", "column", optional=True),
        "train": param("Train fraction", "number", default=0.7, minimum=0.1, maximum=0.9),
        "validation": param("Validation fraction", "number", default=0.15, minimum=0, maximum=0.5),
        "seed": param("Random seed", "number", default=42, minimum=0, maximum=4294967295),
    },
    ("split data for training", "train test split"),
    ("Split before fitting preprocessing. Tiny classes may not appear in every partition.",),
)

from mediasensei.domain.tabular_definitions import define

define()

from mediasensei.asset_operations import register_asset_operations

register_asset_operations()

from mediasensei.batch_definitions import register as register_batch_definitions

register_batch_definitions()

from mediasensei.integration_definitions import register as register_integration_definitions

register_integration_definitions()
