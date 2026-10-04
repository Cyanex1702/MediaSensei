from mediasensei.domain.operations import param, register


def define():
    specs = [
        (
            "statistics",
            "Statistics and frequency tables",
            "Statistics",
            "Inspect schema, memory, quantiles, covariance, unique values and frequencies.",
            {
                "columns": param("Columns"),
                "method": param(
                    "Statistic",
                    "enum",
                    choices=[
                        "describe",
                        "frequency",
                        "unique",
                        "covariance",
                        "quantiles",
                        "memory",
                    ],
                    default="describe",
                ),
            },
        ),
        (
            "duplicates",
            "Inspect duplicate groups",
            "Clean",
            "Assign duplicate groups and mark canonical rows without deleting originals.",
            {
                "columns": param("Match columns"),
                "keep": param("Canonical row", "enum", choices=["first", "last"], default="first"),
            },
        ),
        (
            "exclude",
            "Exclude selected rows",
            "Clean",
            "Remove selected zero-based working row positions; versions retain excluded samples.",
            {"rows": param("Row positions", "json", default=[])},
        ),
        (
            "conditions",
            "Compound row filters",
            "Transform",
            "Combine numeric, category, text, regular expression, date and missing-value conditions.",
            {
                "conditions": param("Conditions", "json", default=[]),
                "match": param("Combine conditions", "enum", choices=["all", "any"], default="all"),
            },
        ),
        (
            "derive",
            "Create arithmetic feature",
            "Transform",
            "Calculate a new feature from column names and arithmetic. No Python code is executed.",
            {
                "name": param("New column name", "string", default="derived"),
                "expression": param("Expression", "string", default="1 + 1"),
            },
        ),
        (
            "strings",
            "Transform text",
            "Transform",
            "Clean case and whitespace, replace text or extract a delimited field.",
            {
                "column": param("Column", "column"),
                "method": param(
                    "Method",
                    "enum",
                    choices=["lower", "upper", "strip", "length", "replace", "split"],
                    default="strip",
                ),
                "value": param("Text or delimiter", "string", default=","),
                "replacement": param("Replacement", "string", default=""),
                "index": param("Field index", "number", default=0, minimum=0, maximum=100),
            },
        ),
        (
            "dates",
            "Date and time features",
            "Transform",
            "Parse UTC dates and extract calendar features or floor timestamps.",
            {
                "column": param("Column", "column"),
                "method": param(
                    "Method",
                    "enum",
                    choices=["year", "month", "day", "weekday", "hour", "floor_day", "floor_month"],
                    default="year",
                ),
                "name": param("New column", "string", default="date_feature"),
            },
        ),
        (
            "replace",
            "Map and replace values",
            "Transform",
            "Replace matching values using an explicit mapping; unmatched values remain unchanged.",
            {"column": param("Column", "column"), "mapping": param("Mapping", "json", default={})},
        ),
        (
            "aggregate",
            "Group and aggregate",
            "Combine",
            "Summarize groups using numeric or count aggregates.",
            {
                "by": param("Group columns"),
                "columns": param("Value columns"),
                "method": param(
                    "Aggregation",
                    "enum",
                    choices=["sum", "mean", "median", "min", "max", "count", "nunique", "std"],
                    default="mean",
                ),
            },
        ),
        (
            "pivot",
            "Pivot table",
            "Transform",
            "Reshape grouped values into columns using an explicit aggregation.",
            {
                "index": param("Row column", "column"),
                "column": param("Column labels", "column"),
                "value": param("Value column", "column"),
                "method": param(
                    "Aggregation",
                    "enum",
                    choices=["sum", "mean", "count", "min", "max"],
                    default="mean",
                ),
            },
        ),
        (
            "melt",
            "Melt into long format",
            "Transform",
            "Keep identifier columns and unpivot other columns into variable/value rows.",
            {"columns": param("Identifier columns")},
        ),
        (
            "explode",
            "Explode delimited values",
            "Transform",
            "Create a row for each value in a delimited cell.",
            {
                "column": param("Column", "column"),
                "separator": param("Separator", "string", default=","),
            },
        ),
        (
            "combine",
            "Join, merge, concatenate or lookup",
            "Combine",
            "Combine this working table with an immutable snapshot of another table.",
            {
                "dataset": param("Other dataset", "dataset"),
                "method": param(
                    "Method",
                    "enum",
                    choices=["left", "inner", "outer", "right", "concat", "lookup"],
                    default="left",
                ),
                "left_on": param("Left key", "column", optional=True),
                "right_on": param("Right key", "string", default=""),
                "validate": param(
                    "Cardinality",
                    "enum",
                    choices=["one_to_one", "one_to_many", "many_to_one", "many_to_many"],
                    default="many_to_one",
                ),
            },
        ),
        (
            "ordinal",
            "Ordinal or label encoding",
            "Features",
            "Encode explicit ordered categories. Unknown values become -1; nulls remain missing.",
            {
                "column": param("Column", "column"),
                "categories": param("Ordered categories", "json", default=[]),
                "name": param("Output column", "string", default="encoded"),
            },
        ),
        (
            "log",
            "Log transform",
            "Features",
            "Apply log1p to numeric values greater than -1.",
            {"columns": param("Numeric columns")},
        ),
        (
            "outliers",
            "Outlier and low variance report",
            "Quality",
            "Inspect IQR or Z-score outliers and low-variance features.",
            {
                "columns": param("Numeric columns"),
                "method": param(
                    "Method", "enum", choices=["iqr", "zscore", "variance"], default="iqr"
                ),
                "threshold": param("Threshold", "number", default=3, minimum=0, maximum=100),
            },
        ),
        (
            "quality",
            "Class balance and leakage checks",
            "Quality",
            "Check class proportions, split overlap, invalid numeric values and target-like features.",
            {
                "target": param("Target column", "column", optional=True),
                "group": param("Group/source column", "column", optional=True),
            },
        ),
        (
            "preprocess",
            "Fit training preprocessing",
            "ML Preparation",
            "Fit imputation, scaling and category vocabulary exclusively on training rows, then transform all partitions.",
            {
                "numeric": param("Numeric features", "json", default=[]),
                "categorical": param("Categorical features", "json", default=[]),
                "method": param(
                    "Scaling", "enum", choices=["standard", "minmax", "robust"], default="standard"
                ),
                "target": param("Target to protect", "column", optional=True),
            },
        ),
        (
            "chart",
            "Chart builder",
            "Visualize",
            "Explore distributions, relationships, categories, time and statistical diagnostics.",
            {
                "kind": param(
                    "Chart",
                    "enum",
                    choices=[
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
                    default="histogram",
                ),
                "x": param("X/category column", "column", optional=True),
                "y": param("Y/value column", "column", optional=True),
                "group": param("Group/size column", "column", optional=True),
                "aggregation": param(
                    "Aggregation",
                    "enum",
                    choices=["count", "mean", "sum", "median"],
                    default="count",
                ),
                "window": param(
                    "Rolling window / bins", "number", default=20, minimum=2, maximum=100
                ),
            },
        ),
    ]
    for identifier, name, category, description, schema in specs:
        register(identifier, name, category, description, schema, aliases=(name.lower(),))
