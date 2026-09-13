"""Windows inbox OCR fallback. No remote service or model download is used."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from mediasensei_plugin_sdk import OCRRegion, OCRResult


class WindowsOCRProvider:
    provider_id = "windows-ocr"
    version = "Windows.Media.Ocr"

    def available(self):
        return os.name == "nt"

    def recognize(self, image_path: Path, *, language=None):
        language = {
            "eng": "en",
            "deu": "de",
            "fra": "fr",
            "spa": "es",
            "urd": "ur",
            "ara": "ar",
            "jpn": "ja",
            "chi_sim": "zh-Hans",
        }.get(language, language or "en")
        executable = (
            Path(os.environ.get("SystemRoot", "C:/Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_name("windows_ocr.ps1")),
                "-ImagePath",
                str(image_path.resolve()),
                "-LanguageTag",
                language,
            ],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError((result.stderr or "Windows OCR failed")[-2000:])
        payload = json.loads(result.stdout)
        return OCRResult(
            text=payload["text"],
            confidence=None,
            regions=tuple(
                OCRRegion(
                    text=r["text"], confidence=None, bounds=tuple(round(v) for v in r["bounds"])
                )
                for r in payload["regions"]
            ),
            language=language,
            provider=self.provider_id,
            provider_version=payload["version"],
        )
