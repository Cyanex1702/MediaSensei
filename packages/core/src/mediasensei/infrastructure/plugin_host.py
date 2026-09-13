from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from mediasensei_plugin_sdk import PluginRegistration, validate_plugin_object

from mediasensei.infrastructure.plugins import MAX_PLUGIN_INPUT_BYTES, MAX_PLUGIN_OUTPUT_BYTES


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_PLUGIN_INPUT_BYTES + 1)
    if len(raw) > MAX_PLUGIN_INPUT_BYTES:
        return _emit_error("PLUGIN_INPUT_TOO_LARGE")
    try:
        request = json.loads(raw)
        if not isinstance(request, dict) or request.get("operation") != "analyze":
            return _emit_error("PLUGIN_REQUEST_INVALID")
        path = Path(str(request["plugin_file"])).resolve()
        if (
            not path.is_file()
            or path.suffix != ".py"
            or path.stat().st_size > MAX_PLUGIN_OUTPUT_BYTES
        ):
            return _emit_error("PLUGIN_SOURCE_INVALID")
        if hashlib.sha256(path.read_bytes()).hexdigest() != request.get("expected_sha256"):
            return _emit_error("PLUGIN_FINGERPRINT_CHANGED")
        spec = importlib.util.spec_from_file_location("mediasensei_isolated_plugin", path)
        if spec is None or spec.loader is None:
            return _emit_error("PLUGIN_IMPORT_INVALID")
        module = importlib.util.module_from_spec(spec)
        with (
            open(os.devnull, "w", encoding="utf-8") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            spec.loader.exec_module(module)
            registration: PluginRegistration = validate_plugin_object(
                getattr(module, "PLUGIN", None)
            )
            index = int(request.get("analyzer_index", 0))
            analyzer = registration.analyzers[index]
            parameters = request.get("parameters", {})
            if not isinstance(parameters, dict):
                return _emit_error("PLUGIN_PARAMETERS_INVALID")
            result = analyzer.analyze(str(request.get("object_key", "")), parameters)
        if not isinstance(result, dict):
            return _emit_error("PLUGIN_RESULT_INVALID")
        encoded = json.dumps({"ok": True, "result": result}, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_PLUGIN_OUTPUT_BYTES:
            return _emit_error("PLUGIN_OUTPUT_TOO_LARGE")
        sys.stdout.write(encoded)
        return 0
    except IndexError:
        return _emit_error("PLUGIN_ANALYZER_NOT_FOUND")
    except Exception:  # noqa: BLE001 - untrusted plugin process boundary
        return _emit_error("PLUGIN_EXECUTION_FAILED")


def _emit_error(code: str) -> int:
    sys.stdout.write(json.dumps({"ok": False, "code": code}, separators=(",", ":")))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
