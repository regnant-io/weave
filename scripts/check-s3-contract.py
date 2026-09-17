"""Exercise Weave's S3-compatible storage contract against a real endpoint.

The script creates the configured bucket when it is absent, writes only beneath a
unique contract-test prefix, and removes every object it creates. Credentials and
the endpoint are read through the normal ``WEAVE_S3_*`` settings.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if not (BACKEND_ROOT / "app").is_dir() and Path("/app/app").is_dir():
    BACKEND_ROOT = Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    if os.getenv("WEAVE_STORAGE_BACKEND", "").lower() != "s3":
        raise SystemExit("WEAVE_STORAGE_BACKEND must be set to s3")

    from app.config import settings
    from app.storage import storage
    from botocore.exceptions import ClientError

    try:
        storage.client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        create_args = {"Bucket": settings.s3_bucket}
        if settings.s3_region and settings.s3_region != "us-east-1":
            create_args["CreateBucketConfiguration"] = {
                "LocationConstraint": settings.s3_region
            }
        storage.client.create_bucket(**create_args)

    prefix = f"contract-tests/{uuid.uuid4().hex}"
    source = f"{prefix}/source.bin"
    copied = f"{prefix}/copy.bin"
    streamed = f"{prefix}/streamed.bin"
    payload = (b"weave-s3-contract\x00" * 8192) + b"complete"

    try:
        assert storage.put_bytes(source, payload) == len(payload)
        assert storage.exists(source)
        assert storage.get_bytes(source) == payload
        assert b"".join(storage.iter_bytes(source, chunk_size=4093)) == payload

        assert storage.put_stream(streamed, io.BytesIO(payload)) == len(payload)
        storage.copy(source, copied)
        assert storage.get_bytes(copied) == payload

        listed = storage.list_prefix(prefix, suffix=".bin")
        assert set(listed) == {source, copied, streamed}

        local = storage.local_path(source)
        assert local.is_file() and local.read_bytes() == payload
        assert storage.local_path(source) == local

        storage.delete(copied)
        assert not storage.exists(copied)
        removed = storage.sweep_prefix(prefix, older_than_seconds=-1)
        assert removed == 2
        assert storage.list_prefix(prefix) == []
    finally:
        for key in (source, copied, streamed):
            storage.delete(key)

    print(f"S3 contract passed for bucket {settings.s3_bucket!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
