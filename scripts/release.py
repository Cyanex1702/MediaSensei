#!/usr/bin/env python3
"""Build and verify reproducible MediaSensei release artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "MediaSensei"
PLATFORMS = ("windows", "linux", "macos")
EXCLUDED_PARTS = {
    ".git",
    ".mediasensei-launcher",
    ".mediasensei-workspace",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vinext",
    "__pycache__",
    "dist",
    "node_modules",
    "release",
    "work",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"}
INCLUDED_ROOTS = (
    ".github",
    "app",
    "apps",
    "components",
    "db",
    "docs",
    "drizzle",
    "hooks",
    "lib",
    "packages",
    "packaging",
    "plugins",
    "public",
    "scripts",
    "tests",
)
TOP_LEVEL = (
    ".env.example",
    "AUDIT_REPORT.md",
    "requirements-lock.txt",
    "setup.bat",
    "start.bat",
    "start-dev.bat",
    "setup.sh",
    "start.sh",
    "start-dev.sh",
    "mediasensei-linux.sh",
    "MediaSensei-macOS.command",
    "MediaSensei-Windows.bat",
    "Stop-MediaSensei-Windows.bat",
    "Update-MediaSensei-Windows.bat",
    ".gitattributes",
    ".openai/hosting.json",
    ".gitignore",
    "CHANGELOG.md",
    "LICENSE",
    "MEDIASENSEI_REPAIR_NOTES.md",
    "README.md",
    "SECURITY.md",
    "components.json",
    "drizzle.config.ts",
    "next.config.ts",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
    "tsconfig.json",
    "vite.config.ts",
)
LAUNCHERS = {
    "windows": (
        "MediaSensei-Windows.bat",
        "Update-MediaSensei-Windows.bat",
        "Stop-MediaSensei-Windows.bat",
    ),
    "linux": ("mediasensei-linux.sh",),
    "macos": ("MediaSensei-macOS.command",),
}


class ReleaseError(RuntimeError):
    pass


def project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    if not match:
        raise ReleaseError("pyproject.toml does not declare a version")
    return match.group(1)


def version_report() -> dict[str, str]:
    values = {"pyproject": project_version()}
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    values["package"] = str(package["version"])
    values["package_lock"] = str(lock["version"])
    values["lock_root"] = str(lock["packages"][""]["version"])
    init_text = (ROOT / "packages/core/src/mediasensei/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE)
    if not match:
        raise ReleaseError("Python package does not declare __version__")
    values["python"] = match.group(1)
    return values


def check_release(*, require_clean: bool = False, tag: str | None = None) -> dict[str, object]:
    versions = version_report()
    if len(set(versions.values())) != 1:
        raise ReleaseError(f"Release versions do not match: {versions}")
    version = next(iter(versions.values()))
    if tag is not None and tag.removeprefix("v") != version:
        raise ReleaseError(f"Release tag {tag} does not match version {version}")
    required = [
        ROOT / name
        for name in (
            "README.md",
            "CHANGELOG.md",
            "SECURITY.md",
            ".env.example",
            "setup.bat",
            "start.bat",
            "setup.sh",
            "start.sh",
            "mediasensei-linux.sh",
            "MediaSensei-macOS.command",
        )
    ]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ReleaseError("Release documentation is missing: " + ", ".join(missing))
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
        if status:
            raise ReleaseError("Release builds require a clean Git working tree")
    return {"version": version, "versions": versions, "tag": tag, "clean_required": require_clean}


def source_date_epoch() -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return max(315532800, int(configured))
    try:
        value = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        return max(315532800, int(value))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 315532800


def release_files(platform: str) -> tuple[Path, ...]:
    if platform not in PLATFORMS:
        raise ReleaseError(f"Unsupported release platform: {platform}")
    selected: set[Path] = set()
    for name in TOP_LEVEL + LAUNCHERS[platform]:
        path = ROOT / name
        if path.is_file():
            selected.add(path)
    for root_name in INCLUDED_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(ROOT)
            if (
                path.is_file()
                and not any(part in EXCLUDED_PARTS for part in relative.parts)
                and not path.name.startswith(".env")
                and path.suffix.casefold() not in SENSITIVE_SUFFIXES | {".pyc", ".pyo"}
            ):
                selected.add(path)
    return tuple(sorted(selected, key=lambda item: item.relative_to(ROOT).as_posix()))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(platform: str, files: Iterable[Path], epoch: int) -> dict[str, object]:
    entries = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        entries.append(
            {
                "path": relative,
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
                "executable": path.suffix in {".sh", ".command"} or relative.startswith("scripts/"),
            }
        )
    return {
        "schema": 1,
        "product": PRODUCT,
        "version": project_version(),
        "platform": platform,
        "created_at": datetime.fromtimestamp(epoch, UTC).isoformat(),
        "requirements": {"python": ">=3.12", "node": ">=22.13.0"},
        "files": entries,
    }


def build_bundle(platform: str, output_dir: Path) -> Path:
    check_release()
    output_dir.mkdir(parents=True, exist_ok=True)
    epoch = source_date_epoch()
    files = release_files(platform)
    payload = (
        json.dumps(manifest(platform, files, epoch), indent=2, sort_keys=True).encode() + b"\n"
    )
    root_name = f"{PRODUCT}-{project_version()}"
    if platform == "windows":
        destination = output_dir / f"{PRODUCT}-{project_version()}-windows.zip"
        timestamp = datetime.fromtimestamp(epoch, UTC).timetuple()[:6]
        with zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                info = zipfile.ZipInfo(f"{root_name}/{relative}", timestamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if path.suffix in {".sh", ".command"} else 0o644) << 16
                archive.writestr(info, path.read_bytes())
            info = zipfile.ZipInfo(f"{root_name}/RELEASE-MANIFEST.json", timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    else:
        destination = output_dir / f"{PRODUCT}-{project_version()}-{platform}.tar.gz"
        with (
            destination.open("wb") as raw,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9
            ) as compressed,
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
        ):
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                tar_info = tarfile.TarInfo(f"{root_name}/{relative}")
                tar_info.size = path.stat().st_size
                tar_info.mtime = epoch
                tar_info.mode = (
                    0o755
                    if path.suffix in {".sh", ".command"} or relative.startswith("scripts/")
                    else 0o644
                )
                tar_info.uid = tar_info.gid = 0
                tar_info.uname = tar_info.gname = ""
                archive.addfile(tar_info, io.BytesIO(path.read_bytes()))
            manifest_info = tarfile.TarInfo(f"{root_name}/RELEASE-MANIFEST.json")
            manifest_info.size = len(payload)
            manifest_info.mtime = epoch
            manifest_info.mode = 0o644
            manifest_info.uid = manifest_info.gid = 0
            manifest_info.uname = manifest_info.gname = ""
            archive.addfile(manifest_info, io.BytesIO(payload))
    verify_bundle(destination)
    return destination


def _archive_entries(path: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0

    def validate(name: str, size: int) -> None:
        nonlocal total
        parts = PurePosixPath(name).parts
        if (
            not parts
            or PurePosixPath(name).is_absolute()
            or ".." in parts
            or "\\" in name
            or ":" in name
            or "\x00" in name
        ):
            raise ReleaseError("Release archive contains an unsafe path")
        folded = name.rstrip("/").casefold()
        if folded in seen:
            raise ReleaseError("Release archive contains a duplicate path")
        seen.add(folded)
        total += size
        if len(seen) > 20000 or size > 64 * 1024**2 or total > 512 * 1024**2:
            raise ReleaseError("Release archive exceeds verification limits")

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for zip_item in archive.infolist():
                validate(zip_item.filename, zip_item.file_size)
                if stat.S_ISLNK(zip_item.external_attr >> 16):
                    raise ReleaseError("Release archive contains a link")
                if not zip_item.is_dir():
                    entries[zip_item.filename] = archive.read(zip_item)
    else:
        with tarfile.open(path, mode="r:gz") as archive:
            for tar_item in archive.getmembers():
                validate(tar_item.name, tar_item.size)
                if not (tar_item.isfile() or tar_item.isdir()):
                    raise ReleaseError("Release archive contains a link or special file")
                if tar_item.isfile():
                    reader = archive.extractfile(tar_item)
                    assert reader is not None
                    entries[tar_item.name] = reader.read()
    return entries


def verify_bundle(path: Path) -> dict[str, object]:
    entries = _archive_entries(path)
    if not entries:
        raise ReleaseError("Release archive is empty")
    names = tuple(entries)
    if any(
        PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names
    ):
        raise ReleaseError("Release archive contains an unsafe path")
    roots = {PurePosixPath(name).parts[0] for name in names}
    if len(roots) != 1:
        raise ReleaseError("Release archive must contain one product root")
    root = next(iter(roots))
    manifest_name = f"{root}/RELEASE-MANIFEST.json"
    if manifest_name not in entries:
        raise ReleaseError("Release archive has no embedded manifest")
    try:
        data = json.loads(entries[manifest_name])
    except json.JSONDecodeError as error:
        raise ReleaseError("Release manifest is invalid JSON") from error
    if (
        not isinstance(data, dict)
        or data.get("schema") != 1
        or data.get("product") != PRODUCT
        or data.get("platform") not in PLATFORMS
        or not isinstance(data.get("version"), str)
        or root != f"{PRODUCT}-{data['version']}"
        or not isinstance(data.get("files"), list)
    ):
        raise ReleaseError("Invalid release manifest schema or identity")
    listed: set[str] = set()
    for item in data["files"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", "")))
            or type(item.get("size")) is not int
            or item["size"] < 0
        ):
            raise ReleaseError("Invalid release manifest file entry")
        if item["path"].casefold() in listed:
            raise ReleaseError("Release manifest contains a duplicate path")
        listed.add(item["path"].casefold())
    expected = {f"{root}/{item['path']}": item for item in data.get("files", [])}
    actual = set(entries) - {manifest_name}
    if set(expected) != actual:
        raise ReleaseError("Release archive contents do not match its manifest")
    for name, item in expected.items():
        digest = hashlib.sha256(entries[name]).hexdigest()
        if digest != item["sha256"] or len(entries[name]) != item["size"]:
            raise ReleaseError(f"Release file verification failed: {name}")
    return {
        "valid": True,
        "path": str(path),
        "version": data["version"],
        "platform": data["platform"],
        "files": len(expected),
    }


def write_checksums(output_dir: Path) -> Path:
    artifacts = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    )
    destination = output_dir / "SHA256SUMS"
    destination.write_text(
        "".join(f"{file_sha256(path)}  {path.name}\n" for path in artifacts), encoding="utf-8"
    )
    return destination


def sign_artifact(path: Path, private_key: Path, signature: Path | None = None) -> Path:
    openssl = shutil.which("openssl")
    if not openssl:
        raise ReleaseError("OpenSSL is required for detached release signatures")
    if not path.is_file() or not private_key.is_file():
        raise ReleaseError("The artifact and private signing key must exist")
    destination = signature or path.with_suffix(path.suffix + ".sig")
    subprocess.run(
        [
            openssl,
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(destination),
            str(path),
        ],
        check=True,
        shell=False,
    )
    return destination


def verify_signature(path: Path, public_key: Path, signature: Path) -> bool:
    openssl = shutil.which("openssl")
    if not openssl:
        raise ReleaseError("OpenSSL is required to verify release signatures")
    completed = subprocess.run(
        [
            openssl,
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature),
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise ReleaseError("Detached release signature verification failed")
    return True


def build_python(output_dir: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output_dir)],
        cwd=ROOT,
        check=True,
        shell=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--require-clean", action="store_true")
    check_parser.add_argument("--tag")
    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("--platform", choices=PLATFORMS + ("all",), default="all")
    bundle_parser.add_argument("--output", type=Path, default=ROOT / "release")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("archive", type=Path)
    python_parser = subparsers.add_parser("build-python")
    python_parser.add_argument("--output", type=Path, default=ROOT / "release")
    checksum_parser = subparsers.add_parser("checksums")
    checksum_parser.add_argument("--output", type=Path, default=ROOT / "release")
    sign_parser = subparsers.add_parser("sign")
    sign_parser.add_argument("artifact", type=Path)
    sign_parser.add_argument("--private-key", type=Path, required=True)
    sign_parser.add_argument("--signature", type=Path)
    verify_signature_parser = subparsers.add_parser("verify-signature")
    verify_signature_parser.add_argument("artifact", type=Path)
    verify_signature_parser.add_argument("--public-key", type=Path, required=True)
    verify_signature_parser.add_argument("--signature", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(
                json.dumps(check_release(require_clean=args.require_clean, tag=args.tag), indent=2)
            )
        elif args.command == "bundle":
            selected = PLATFORMS if args.platform == "all" else (args.platform,)
            for platform in selected:
                artifact = build_bundle(platform, args.output)
                print(json.dumps(verify_bundle(artifact), indent=2))
            write_checksums(args.output)
        elif args.command == "verify":
            print(json.dumps(verify_bundle(args.archive), indent=2))
        elif args.command == "build-python":
            args.output.mkdir(parents=True, exist_ok=True)
            build_python(args.output)
        elif args.command == "checksums":
            print(write_checksums(args.output))
        elif args.command == "sign":
            print(sign_artifact(args.artifact, args.private_key, args.signature))
        else:
            verify_signature(args.artifact, args.public_key, args.signature)
            print("Signature verified")
        return 0
    except (OSError, ReleaseError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
