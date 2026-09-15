"""S3-compatible object storage abstraction (architecture section 2: object storage).

Dev default is a local-filesystem backend so datasets/charts/exports work with no
cloud account. The interface matches an S3 client closely enough that swapping in
boto3 (WEAVE_STORAGE_BACKEND=s3) touches only this file.
"""
from __future__ import annotations

import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO, Iterator

from .config import settings


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        """Resolve a key to a path, refusing anything outside the root.

        The containment test is `is_relative_to`, not a string prefix. A prefix
        comparison accepts a SIBLING whose name merely starts with the root's:
        with a root of `/var/storage`, the key `../storage-public/x` resolves to
        `/var/storage-public/x`, and `str(p).startswith("/var/storage")` is
        perfectly true. Path-aware containment compares components, so it cannot
        be fooled that way.
        """
        p = (self.root / key).resolve()
        root = self.root.resolve()
        if p != root and not p.is_relative_to(root):
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

    def iter_bytes(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        with open(self._path(key), "rb") as source:
            while chunk := source.read(chunk_size):
                yield chunk

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


class S3Storage:
    """S3-compatible storage with bounded local materialisation for analysis."""

    def __init__(self) -> None:
        import boto3

        kwargs = {
            "region_name": settings.s3_region,
            "endpoint_url": settings.s3_endpoint_url,
        }
        if settings.s3_access_key_id:
            kwargs["aws_access_key_id"] = settings.s3_access_key_id
        if settings.s3_secret_access_key:
            kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
        self.client = boto3.client("s3", **kwargs)
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_key_prefix.strip("/")
        self.cache = Path(settings.s3_cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def _key(self, key: str) -> str:
        clean = PurePosixPath(str(key).replace("\\", "/"))
        if clean.is_absolute() or ".." in clean.parts:
            raise ValueError("invalid storage key")
        value = clean.as_posix().lstrip("./")
        if not value:
            raise ValueError("invalid storage key")
        return f"{self.prefix}/{value}" if self.prefix else value

    def put_stream(self, key: str, fileobj: BinaryIO) -> int:
        remote = self._key(key)
        self.client.upload_fileobj(fileobj, self.bucket, remote)
        return int(self.client.head_object(Bucket=self.bucket, Key=remote)["ContentLength"])

    def put_bytes(self, key: str, data: bytes) -> int:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)
        return len(data)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()

    def iter_bytes(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"]
        try:
            for chunk in body.iter_chunks(chunk_size=chunk_size):
                if chunk:
                    yield chunk
        finally:
            body.close()

    def local_path(self, key: str) -> Path:
        remote = self._key(key)
        suffix = Path(key).suffix
        target = self.cache / f"{hashlib.sha256(remote.encode()).hexdigest()}{suffix}"
        if not target.exists():
            temp = target.with_suffix(target.suffix + ".tmp")
            self.client.download_file(self.bucket, remote, str(temp))
            temp.replace(target)
        return target

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def copy(self, src_key: str, dst_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            Key=self._key(dst_key),
            CopySource={"Bucket": self.bucket, "Key": self._key(src_key)},
        )

    def list_prefix(self, prefix: str, suffix: str = "") -> list[str]:
        remote_prefix = self._key(prefix).rstrip("/") + "/"
        paginator = self.client.get_paginator("list_objects_v2")
        found: list[tuple[datetime, str]] = []
        trim = f"{self.prefix}/" if self.prefix else ""
        for page in paginator.paginate(Bucket=self.bucket, Prefix=remote_prefix):
            for item in page.get("Contents", []):
                key = str(item["Key"])
                public = key[len(trim):] if key.startswith(trim) else key
                if not suffix or public.endswith(suffix):
                    found.append((item["LastModified"], public))
        found.sort(reverse=True)
        return [key for _, key in found]

    def sweep_prefix(self, prefix: str, older_than_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        removed = 0
        remote_prefix = self._key(prefix).rstrip("/") + "/"
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=remote_prefix):
            expired = [
                {"Key": item["Key"]}
                for item in page.get("Contents", [])
                if item["LastModified"].timestamp() < cutoff
            ]
            if expired:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": expired})
                removed += len(expired)
        return removed


def _build_storage():
    if settings.storage_backend == "s3":  # pragma: no cover - requires S3 credentials
        return S3Storage()
    return LocalStorage(settings.storage_local_dir)


storage = _build_storage()
