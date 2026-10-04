"""Compile a restricted Python call syntax into existing typed table operations."""

from __future__ import annotations

import ast
import json

from mediasensei.domain.operations import REGISTRY


def compile_script(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > 16384:
        raise ValueError("Playground source must be nonempty and at most 16 KiB.")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"Invalid syntax on line {error.lineno}.") from None
    if len(list(ast.walk(tree))) > 2000 or not 1 <= len(tree.body) <= 30:
        raise ValueError("A script supports at most 30 bounded operation calls.")
    steps = []
    for statement in tree.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "data"
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
        ):
            raise ValueError(
                "Use data = operation(data, parameter=value). Imports, loops and arbitrary code are unavailable."
            )
        call = statement.value
        if (
            len(call.args) != 1
            or not isinstance(call.args[0], ast.Name)
            or call.args[0].id != "data"
        ):
            raise ValueError("The only positional argument must be data.")
        try:
            definition = REGISTRY.get(call.func.id)
        except KeyError:
            raise ValueError(f"Unknown table operation: {call.func.id}") from None
        if definition.modality != "tabular" or definition.input_types != ("TabularDataset",):
            raise ValueError("Playground accepts registered table operations only.")
        parameters = {}
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg in parameters:
                raise ValueError("Expanded or repeated keyword arguments are not supported.")
            try:
                parameters[keyword.arg] = ast.literal_eval(keyword.value)
                json.dumps(parameters[keyword.arg], allow_nan=False)
            except (ValueError, TypeError, SyntaxError):
                raise ValueError(
                    "Parameters must be JSON-compatible literals, not expressions or calls."
                ) from None
        if set(parameters) - set(definition.parameter_schema):
            raise ValueError("Unknown operation parameter.")
        steps.append({"operation": definition.id, "parameters": parameters})
    return steps
