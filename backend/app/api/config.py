"""Runtime config + model discovery + artifact serving."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import settings
from ..deps import get_current_user
from ..models import User
from ..runtime import EFFORT_SPEC, current, set_ollama
from ..schemas import OllamaConfig
from ..storage import storage

router = APIRouter()


@router.get("/models")
def list_models(_user: User = Depends(get_current_user)) -> dict:
    """Models available on the configured Ollama server (for the model picker).

    Each entry carries its effective context window so the composer can track
    usage against the real limit instead of guessing.
    """
    from ..services.orchestration.llm import OllamaEngine, get_engine
    engine = get_engine()
    ollama = engine if getattr(engine, "name", "") == "ollama" else None
    if ollama is None:
        try:
            ollama = OllamaEngine()
        except Exception:  # noqa: BLE001 - no Ollama configured; empty picker
            ollama = None

    names: list[str] = ollama.list_models() if ollama else []
    models = []
    for n in names:
        ctx = None
        if ollama is not None:
            try:
                ctx = ollama.effective_context(n)
            except Exception:  # noqa: BLE001 - one bad model must not 500 the list
                ctx = None
        models.append({"name": n, "context": ctx})

    cfg = current()
    return {
        "models": models,
        "current_model": cfg["ollama_model"],
        "engine": getattr(engine, "name", "offline"),
        # Fallback window (used when a model's own window can't be read) and the
        # ceiling we will request from a model that advertises more.
        "num_ctx_fallback": settings.ollama_num_ctx,
        "num_ctx_ceiling": settings.ollama_max_num_ctx,
    }


@router.get("/ollama")
def get_ollama(_user: User = Depends(get_current_user)) -> dict:
    return current()


@router.post("/ollama")
def set_ollama_config(body: OllamaConfig, _user: User = Depends(get_current_user)) -> dict:
    set_ollama(host=body.host, model=body.model)
    return current()


@router.get("/effort")
def list_effort(_user: User = Depends(get_current_user)) -> dict:
    return {"levels": [{"id": k, "label": v["label"]} for k, v in EFFORT_SPEC.items()]}


# --- artifact serving (charts/decks/pdfs/3d) -------------------------------
_MIME_BY_EXT = {
    ".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".pdf": "application/pdf", ".html": "text/html",
    ".csv": "text/csv", ".json": "application/json", ".glb": "model/gltf-binary",
}


@router.get("/artifacts/{key:path}")
def get_artifact(key: str, sig: str = "") -> Response:
    """Serve a stored artifact. Requires a valid HMAC signature (sig) so URLs
    can't be forged or enumerated; served without a session so <img>/<iframe>
    can load it directly."""
    from ..security import verify_path
    if not verify_path(key, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid signature")
    if not storage.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found")
    data = storage.get_bytes(key)
    ext = "." + key.rsplit(".", 1)[-1].lower() if "." in key else ""
    mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"})
