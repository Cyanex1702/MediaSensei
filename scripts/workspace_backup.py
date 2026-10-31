#!/usr/bin/env python3
"""Offline portable workspace backup and safe restore to a new directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def backup(source: Path, output: Path):
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ValueError("Workspace does not exist")
    if output.is_relative_to(source):
        raise ValueError("Save backups outside the workspace")
    if output.exists():
        raise ValueError("Backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    temporary = output.with_suffix(".partial")
    try:
        with (
            tempfile.TemporaryDirectory() as scratch,
            zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive,
        ):
            # Caller stops API/worker first. SQLite backup also makes WAL state portable.
            for path in sorted(source.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(source).as_posix()
                if any(
                    part in {"temp", "logs"} for part in path.relative_to(source).parts
                ) or path.name.endswith(("-wal", "-shm")):
                    continue
                selected = path
                if path.suffix == ".db":
                    selected = Path(scratch) / hashlib.sha256(relative.encode()).hexdigest()
                    with (
                        closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as src,
                        closing(sqlite3.connect(selected)) as dst,
                    ):
                        src.backup(dst)
                digest = hashlib.sha256()
                with (
                    selected.open("rb") as stream,
                    archive.open("workspace/" + relative, "w") as target,
                ):
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
                manifest[relative] = digest.hexdigest()
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {"schema": 1, "created_at": datetime.now(UTC).isoformat(), "files": manifest},
                    indent=2,
                ),
            )
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return output


def restore(archive_path: Path, destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Restore requires a new destination; existing data is never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema") != 1:
                raise ValueError("Unsupported backup format")
            total = sum(item.file_size for item in archive.infolist())
            if total > shutil.disk_usage(staging).free:
                raise ValueError("Insufficient free space for restore")
            for name, expected in manifest["files"].items():
                target = (staging / name).resolve()
                if not target.is_relative_to(staging) or target == staging:
                    raise ValueError("Unsafe backup path")
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open("workspace/" + name) as src, target.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        digest.update(chunk)
                        dst.write(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError(f"Checksum mismatch: {name}")
            staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--archive")
    parser.add_argument("--destination")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if args.action == "backup":
        import mediasensei_launcher as launcher

        launcher.stop()
        from apps.api.config import settings

        output = (
            Path(args.archive)
            if args.archive
            else root / "backups" / f"MediaSensei-{datetime.now():%Y%m%d-%H%M%S}.zip"
        )
        print("Backup saved:", backup(settings.workspace, output))
        print(
            "Restart MediaSensei with MediaSensei-Windows.bat. Credentials remain in the OS credential store and are not included."
        )
    else:
        if not args.archive or not args.destination:
            parser.error("Restore requires --archive and --destination")
        if args.activate:
            import mediasensei_launcher as launcher

            launcher.stop()
        restored = restore(Path(args.archive), Path(args.destination))
        if args.activate:
            from dotenv import set_key

            set_key(str(root / ".env"), "MEDIASENSEI_WORKSPACE", str(restored))
        print("Restored:", restored)
        print(
            "Set MEDIASENSEI_WORKSPACE in .env to this new folder while the app is stopped. Re-save provider credentials for its new location."
        )


if __name__ == "__main__":
    main()
