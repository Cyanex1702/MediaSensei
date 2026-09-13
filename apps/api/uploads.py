"""Bounded upload storage and platform-independent ZIP validation."""
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException, UploadFile


def fail(code, message, status=422):
    raise HTTPException(status, detail={"code": code, "message": message})


def write_upload(file: UploadFile, root: Path, limit: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # User filenames never become temporary filesystem paths (Windows devices/ADS).
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
        temporary = Path(output.name)
        size = 0
        try:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    fail("UPLOAD_TOO_LARGE", f"Upload exceeds {limit} bytes", 413)
                output.write(chunk)
            if not size:
                fail("EMPTY_FILE", "Empty files cannot be imported")
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    return temporary


@contextmanager
def extract_archive(source: Path, root: Path, settings, classify):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archive-", dir=root) as directory:
        members, skipped, seen = [], [], set()
        total = 0
        try:
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if len(infos) > settings.zip_max_files:
                    fail("ZIP_TOO_MANY_FILES", f"ZIP exceeds {settings.zip_max_files} entries", 413)
                for info in infos:
                    if info.is_dir():
                        continue
                    name = info.filename.replace(chr(92), "/")
                    parts = name.split("/")
                    mode = info.external_attr >> 16
                    if (name.startswith("/") or PureWindowsPath(name).drive or
                        any(part in {"", ".", ".."} or ":" in part for part in parts) or
                        stat.S_ISLNK(mode)):
                        skipped.append({"name": info.filename, "reason": "unsafe path"})
                        continue
                    if name.casefold() in seen:
                        skipped.append({"name": name, "reason": "duplicate archive path"})
                        continue
                    seen.add(name.casefold())
                    if not classify(parts[-1]):
                        skipped.append({"name": name, "reason": "unsupported file type"})
                        continue
                    if not info.file_size:
                        skipped.append({"name": name, "reason": "empty file"})
                        continue
                    if info.flag_bits & 1:
                        fail("ENCRYPTED_ZIP", "Password-protected ZIP files are not supported")
                    if info.file_size > settings.max_upload_bytes:
                        fail("ZIP_MEMBER_TOO_LARGE", "A ZIP member exceeds the upload limit", 413)
                    total += info.file_size
                    if total > settings.zip_max_total_bytes:
                        fail("ZIP_TOO_LARGE", "Extracted ZIP exceeds the configured size limit", 413)
                    # Flatten staging names; preserve original display names in the catalog.
                    destination = Path(directory) / str(len(members))
                    copied = 0
                    with archive.open(info) as reader, destination.open("xb") as writer:
                        while chunk := reader.read(1024 * 1024):
                            copied += len(chunk)
                            if copied > info.file_size or copied > settings.max_upload_bytes:
                                fail("ZIP_MEMBER_TOO_LARGE", "ZIP member exceeds its declared size", 413)
                            writer.write(chunk)
                    members.append((destination, parts[-1]))
            if not members:
                fail("ZIP_NO_SUPPORTED_FILES", "ZIP contains no non-empty supported files")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
            raise HTTPException(422, detail={"code": "INVALID_ZIP", "message": "ZIP is corrupt, encrypted, or uses unsupported compression"}) from error
        # No catalog writes occur until the whole archive has passed extraction/CRC checks.
        yield members, skipped
