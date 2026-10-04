"""Configure native media tools without changing the system PATH."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-dir", type=Path, help="Folder containing ffmpeg and ffprobe")
    parser.add_argument(
        "--tesseract",
        type=Path,
        help="Optional Tesseract executable; Windows has an inbox OCR fallback",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    values = {}
    if args.ffmpeg_dir:
        suffix = ".exe" if os.name == "nt" else ""
        for name in ("ffmpeg", "ffprobe"):
            executable = (args.ffmpeg_dir / (name + suffix)).resolve(strict=True)
            subprocess.run(
                [str(executable), "-version"],
                check=True,
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            values["MEDIASENSEI_" + name.upper()] = executable.as_posix()
    if args.tesseract:
        executable = args.tesseract.resolve(strict=True)
        subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        values["MEDIASENSEI_TESSERACT"] = executable.as_posix()
    if not values:
        parser.error("Provide --ffmpeg-dir or --tesseract.")
    env = root / ".env"
    if not env.exists():
        shutil.copyfile(root / ".env.example", env)
    content = env.read_text(encoding="utf-8")
    for key, value in values.items():
        if "\n" in value or '"' in value:
            raise ValueError("Tool path contains unsupported characters.")
        content = re.sub(r"^" + key + r"=.*\n?", "", content, flags=re.MULTILINE)
        content += f'\n{key}="{value}"\n'
    env.write_text(content, encoding="utf-8")
    print("Native tools verified and configured. Restart MediaSensei to apply.")


if __name__ == "__main__":
    main()
