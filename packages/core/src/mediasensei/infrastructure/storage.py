from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredObject:
    sha256: str
    object_key: str
    path: Path
    byte_size: int
    already_existed: bool


class ContentAddressedStore:
    """Immutable SHA-256 object storage.

    Importing never mutates the source. Identical bytes resolve to one physical object.
    """

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.object_root = self.workspace / "objects" / "sha256"
        self.temp_root = self.workspace / "temp"
        self.object_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def import_file(self, source: str | Path) -> StoredObject:
        source_path = Path(source).expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise ValueError(f"Asset source is not a regular file: {source_path}")

        digest = hashlib.sha256()
        with source_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        sha256 = digest.hexdigest()
        destination = self.object_root / sha256[:2] / sha256
        object_key = destination.relative_to(self.workspace).as_posix()

        if destination.exists():
            return StoredObject(sha256, object_key, destination, source_path.stat().st_size, True)

        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f"{sha256}.", dir=self.temp_root)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            shutil.copyfile(source_path, temporary)
            if self._sha256(temporary) != sha256:
                raise OSError("Copied object failed SHA-256 integrity verification")
            try:
                os.replace(temporary, destination)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)

        return StoredObject(sha256, object_key, destination, source_path.stat().st_size, False)

    def resolve(self, object_key: str) -> Path:
        """Resolve a catalog object key without permitting workspace traversal."""
        if not object_key or "\\" in object_key:
            raise ValueError("Object keys must use normalized forward-slash paths")
        candidate = (self.workspace / object_key).resolve()
        try:
            candidate.relative_to(self.object_root)
        except ValueError as error:
            raise ValueError("Object key escapes content-addressed storage") from error
        if not candidate.is_file():
            raise FileNotFoundError(f"Stored object does not exist: {object_key}")
        return candidate

    def verify(self, sha256: str) -> bool:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            return False
        path = self.object_root / sha256[:2] / sha256
        return path.is_file() and self._sha256(path) == sha256

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
