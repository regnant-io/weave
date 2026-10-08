"""Inspection output helpers; completion and retry policy belong to Agent."""
from __future__ import annotations

import base64
import uuid


def store_preview(screenshot: str) -> str:
    """Return a signed URL for a captured preview, or nothing on storage failure."""
    from ...security import artifact_url
    from ...storage import storage

    try:
        data = base64.b64decode(screenshot, validate=True)
        if not data:
            return ""
        key = f"render/preview_{uuid.uuid4().hex}.jpg"
        storage.put_bytes(key, data)
        return artifact_url(key)
    except Exception:
        return ""
