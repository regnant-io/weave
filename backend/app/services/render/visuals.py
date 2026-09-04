"""Registry for AI-generated visuals.

Generating a visual is easy; *revising* one is what makes the model usable as a
collaborator. "Make the axis log scale", "drop the 2019 outlier", "use the same
chart but for Mwanza" should all edit an existing artifact rather than pile up
seven near-identical ones in the panel.

That needs a stable handle. Each visual gets a short id and lives at a
deterministic key, so re-rendering overwrites in place and the URL the user
already has open keeps working. A JSON sidecar stores the spec that produced it,
which is what makes a partial update ("just change the title") possible without
the model having to restate the whole thing.

Layout:
    visuals/{project_id}/{visual_id}.html   the rendered artifact
    visuals/{project_id}/{visual_id}.json   {title, kind, spec, tool, created_at}
    visuals/{project_id}/{visual_id}.src.json  the bulky inputs, kept apart

WHY THE SOURCE IS A SEPARATE FILE

Two of the things that make a visual are large: a Babylon scene is hundreds of
lines of code, and its meshes and textures travel with it as data URLs. Putting
those in the metadata sidecar looks tidier and is quietly disastrous, because
`listing()` reads EVERY sidecar in the project to answer `list_visuals` -- a
question that only needs titles. One 20MB scene would make listing five visuals
a 20MB read.

So the sidecar stays small and structured, and the bulk lives in its own key
that is fetched only when something actually needs to edit the visual. That is
what makes repair-by-editing possible at all: to change one line of a broken
scene the model has to be able to see the other lines, and before this the only
copy of them was inside the rendered HTML.
"""
from __future__ import annotations

import json
import time
import uuid

from ...storage import storage

PREFIX = "visuals"


def _safe(part: str) -> str:
    """Keep ids filesystem-safe; storage also blocks traversal, this is belt+braces."""
    return "".join(c for c in str(part) if c.isalnum() or c in "-_")[:64] or "x"


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def html_key(project_id: str, visual_id: str) -> str:
    return f"{PREFIX}/{_safe(project_id)}/{_safe(visual_id)}.html"


def meta_key(project_id: str, visual_id: str) -> str:
    return f"{PREFIX}/{_safe(project_id)}/{_safe(visual_id)}.json"


def source_key(project_id: str, visual_id: str) -> str:
    return f"{PREFIX}/{_safe(project_id)}/{_safe(visual_id)}.src.json"


def save(project_id: str, visual_id: str, html: str, meta: dict,
         source: dict | None = None) -> dict:
    """Persist (or overwrite) a visual, its spec sidecar and its source.

    `source` holds whatever is too big for the sidecar -- scene code, page HTML,
    inlined assets. It is written only when supplied, so a caller that has
    nothing bulky to store leaves no extra key behind.
    """
    hk = html_key(project_id, visual_id)
    storage.put_bytes(hk, html.encode("utf-8"))
    record = {
        "visual_id": visual_id,
        "created_at": meta.get("created_at") or time.time(),
        "updated_at": time.time(),
        **meta,
    }
    storage.put_bytes(meta_key(project_id, visual_id), json.dumps(record).encode("utf-8"))
    if source:
        storage.put_bytes(source_key(project_id, visual_id),
                          json.dumps(source).encode("utf-8"))
    return {"key": hk, "record": record}


def load_source(project_id: str, visual_id: str) -> dict:
    """The bulky inputs that produced this visual, or {}.

    This is what makes editing possible rather than regenerating. A model asked
    to fix one broken line in a scene it wrote twenty minutes ago has no memory
    of the other four hundred; without the source the only thing it can do is
    write the whole thing again, which reliably reintroduces a different fault.
    """
    sk = source_key(project_id, visual_id)
    if not storage.exists(sk):
        return {}
    try:
        return json.loads(storage.get_bytes(sk).decode("utf-8")) or {}
    except (ValueError, OSError):
        return {}


def load_html(project_id: str, visual_id: str) -> str:
    """The stored page itself, so a visual can be re-checked after the fact.

    Returns "" when the visual does not exist — callers treat a missing artifact
    and an empty one the same way.
    """
    hk = html_key(project_id, visual_id)
    if not storage.exists(hk):
        return ""
    try:
        return storage.get_bytes(hk).decode("utf-8")
    except (ValueError, OSError):
        return ""


def load_meta(project_id: str, visual_id: str) -> dict | None:
    mk = meta_key(project_id, visual_id)
    if not storage.exists(mk):
        return None
    try:
        return json.loads(storage.get_bytes(mk).decode("utf-8"))
    except (ValueError, OSError):
        return None


def listing(project_id: str) -> list[dict]:
    """Every visual in a project, newest first, without their HTML bodies."""
    out: list[dict] = []
    for key in storage.list_prefix(f"{PREFIX}/{_safe(project_id)}", suffix=".json"):
        try:
            rec = json.loads(storage.get_bytes(key).decode("utf-8"))
        except (ValueError, OSError):
            continue
        out.append({
            "visual_id": rec.get("visual_id"),
            "title": rec.get("title"),
            "kind": rec.get("kind"),
            "tool": rec.get("tool"),
            "updated_at": rec.get("updated_at"),
        })
    return out


def delete(project_id: str, visual_id: str) -> bool:
    hk = html_key(project_id, visual_id)
    existed = storage.exists(hk) or storage.exists(meta_key(project_id, visual_id))
    storage.delete(hk)
    storage.delete(meta_key(project_id, visual_id))
    storage.delete(source_key(project_id, visual_id))
    return existed


def merge_spec(old: dict, patch: dict) -> dict:
    """Shallow-merge a spec patch over the stored spec.

    Shallow is the right depth here: specs are flat-ish, and a deep merge would
    make it impossible to REPLACE a list (new nodes, new curves) — the model
    would only ever be able to append. Replacing a key wholesale is predictable.
    """
    out = dict(old or {})
    for k, v in (patch or {}).items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out
