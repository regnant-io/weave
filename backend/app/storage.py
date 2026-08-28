"""S3-compatible object storage abstraction (architecture section 2: object storage).

Dev default is a local-filesystem backend so datasets/charts/exports work with no
cloud account. The interface matches an S3 client closely enough that swapping in
boto3 (WEAVE_STORAGE_BACKEND=s3) touches only this file.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from .config import settings


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # prevent path traversal outside the storage root
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid storage key")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_stream(self, key: str, fileobj: BinaryIO) -> int:
        path = self._path(key)
        size = 0
        with open(path, "wb") as out:
            while chunk := fileobj.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        return size

    def put_bytes(self, key: str, data: bytes) -> int:
        path = self._path(key)
        path.write_bytes(data)
        return len(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def local_path(self, key: str) -> Path:
        """Absolute path on disk — used to give the Sandbox Manager a read-only
        copy-on-write mount source (architecture 8.2 step 2)."""
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def copy(self, src_key: str, dst_key: str) -> None:
        shutil.copy2(self._path(src_key), self._path(dst_key))

    def list_prefix(self, prefix: str, suffix: str = "") -> list[str]:
        """Keys under a prefix, newest first.

        Needed so the model can enumerate the visuals it has already produced in
        a project and then update or delete them by id, rather than only ever
        being able to append new ones.
        """
        base = self.root / prefix
        if not base.exists():
            return []
        items: list[tuple[float, str]] = []
        root = self.root.resolve()
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if suffix and not p.name.endswith(suffix):
                continue
            try:
                items.append((p.stat().st_mtime, p.resolve().relative_to(root).as_posix()))
            except (OSError, ValueError):
                continue
        items.sort(reverse=True)
        return [k for _, k in items]

    def sweep_prefix(self, prefix: str, older_than_seconds: int) -> int:
        """Delete files under a prefix older than the cutoff. Returns count removed.
        Used to garbage-collect generated artifacts (charts/decks/pdfs)."""
        import time
        base = (self.root / prefix)
        if not base.exists():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for p in base.rglob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


def _build_storage():
    if settings.storage_backend == "s3":  # pragma: no cover - requires boto3 + creds
        raise NotImplementedError(
            "S3 backend: install boto3 and implement here; interface mirrors LocalStorage."
        )
    return LocalStorage(settings.storage_local_dir)


storage = _build_storage()
