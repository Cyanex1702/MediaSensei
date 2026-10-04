"""Opt-in local Windows speech provider."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def native_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
    }


def speech_request(request):
    if os.name != "nt":
        raise ValueError("This speech adapter requires Windows and an installed system voice.")
    executable = (
        Path(os.environ.get("SystemRoot", "C:/Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    with tempfile.TemporaryDirectory(prefix="mediasensei-speech-") as directory:
        path = Path(directory) / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_name("native_speech.ps1")),
                "-RequestFile",
                str(path),
            ],
            env=native_environment(),
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError("Local speech failed; check the installed voice and language.")
        return json.loads(result.stdout)


def installed_voices():
    if os.name != "nt":
        return []
    return speech_request({"action": "voices"})


def speak(catalog, source, asset, parameters, directory):
    from mediasensei.knowledge import prepare_document
    from mediasensei.operations import parameters as operation_parameters

    with catalog.connect() as db:
        voice = db.execute(
            "SELECT * FROM voice_personalities WHERE id=?", (parameters["personality"],)
        ).fetchone()
    if not voice:
        raise ValueError("Voice personality is unavailable.")
    parsed = prepare_document(source, asset, operation_parameters("document.prepare", {}, []))
    text = "\n".join(block.text for block in parsed.blocks)
    if not text.strip() or len(text) > 5000:
        raise ValueError("Speech requires a document containing 1–5000 characters.")
    path = directory / "speech.wav"
    report = speech_request(
        {
            "action": "speak",
            "voice": voice["voice"],
            "rate": voice["rate"],
            "text": text,
            "output": str(path),
        }
    )
    if not path.is_file() or path.stat().st_size <= 44:
        raise ValueError("Speech provider produced no audio.")
    report.update(
        tool_revision=report["version"],
        personality=voice["id"],
        rate=voice["rate"],
        characters=len(text),
    )
    return report, [(path, "audio/wav")]

