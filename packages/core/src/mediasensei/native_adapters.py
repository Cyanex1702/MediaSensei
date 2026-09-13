"""Opt-in local speech and transcription providers; no model downloads."""

from __future__ import annotations

import hashlib
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


def asr_available():
    return all(
        Path(os.environ.get(key, "")).is_file()
        for key in ("MEDIASENSEI_WHISPER_CPP", "MEDIASENSEI_WHISPER_MODEL")
    )


def asr_revisions():
    if not asr_available():
        raise ValueError("Configure local MEDIASENSEI_WHISPER_CPP and MEDIASENSEI_WHISPER_MODEL.")
    revisions = {}
    for key, variable in (
        ("model_revision", "MEDIASENSEI_WHISPER_MODEL"),
        ("tool_revision", "MEDIASENSEI_WHISPER_CPP"),
    ):
        path = Path(os.environ[variable])
        if path.stat().st_size > 4 * 1024**3:
            raise ValueError("ASR tool/model exceeds the 4 GiB limit.")
        with path.open("rb") as stream:
            revisions[key] = hashlib.file_digest(stream, "sha256").hexdigest()
    return revisions


def transcribe(store, source, parameters, directory):
    from mediasensei.infrastructure.media import FFmpegToolchain

    if not asr_available():
        raise ValueError(
            "Configure local MEDIASENSEI_WHISPER_CPP and MEDIASENSEI_WHISPER_MODEL; no model is downloaded automatically."
        )
    model = Path(os.environ["MEDIASENSEI_WHISPER_MODEL"])
    executable = Path(os.environ["MEDIASENSEI_WHISPER_CPP"])
    if model.stat().st_size > 4 * 1024**3:
        raise ValueError("ASR model exceeds the 4 GiB limit.")
    revisions = asr_revisions()
    if any(parameters.get(key) != value for key, value in revisions.items()):
        raise ValueError("ASR tool/model changed since this job was queued.")
    tools = FFmpegToolchain()
    wave = directory / "input.wav"
    tools._run(
        [
            str(tools.ffmpeg),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-t",
            str(parameters["duration"]),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-threads",
            "1",
            "-y",
            str(wave),
        ],
        timeout=120,
    )
    prefix = directory / "transcript"
    with (directory / "asr.log").open("wb") as log:
        result = subprocess.run(
            [
                str(executable),
                "-m",
                str(model),
                "-f",
                str(wave),
                "-t",
                "2",
                "-ng",
                "-l",
                parameters["language"],
                "-otxt",
                "-of",
                str(prefix),
            ],
            env=native_environment(),
            stdout=log,
            stderr=log,
            timeout=1800,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    output = prefix.with_suffix(".txt")
    if result.returncode or not output.is_file() or output.stat().st_size > 2 * 1024**2:
        raise ValueError("Local transcription failed or exceeded the output limit.")
    if asr_revisions() != revisions:
        raise ValueError("ASR tool/model changed during transcription.")
    return {
        **revisions,
        "provider": "whisper.cpp",
        "duration_limit": parameters["duration"],
        "language": parameters["language"],
    }, [(output, "text/plain")]
