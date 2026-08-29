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
        trained = None
        if ollama is not None:
            try:
                ctx = ollama.effective_context(n)
                trained = ollama.model_context(n)
            except Exception:  # noqa: BLE001 - one bad model must not 500 the list
                ctx = None
        caps: list[str] = []
        klass = "small"
        if ollama is not None:
            try:
                caps = sorted(ollama.capabilities(n))
                klass = ollama.model_class(n)
            except Exception:  # noqa: BLE001 - one bad model must not 500 the list
                pass
        models.append({
            "name": n,
            # What we will actually request (and draw the meter against).
            "context": ctx,
            # What the model itself advertises, so the UI can show when a
            # configured ceiling is costing the user window.
            "trained_context": trained,
            # 'tools' is the one that decides whether Weave is a working
            # instrument or a chat window on this model, so the picker shows it
            # rather than letting the user discover it mid-turn.
            "capabilities": caps,
            "supports_tools": ("tools" in caps) if caps else True,
            "class": klass,
        })

    cfg = current()
    configured = cfg["ollama_model"]
    # What will REALLY answer, which is not always what is configured: a model
    # named in .env but never pulled used to fail silently into the offline
    # engine. The picker shows the resolved model and says when it differs.
    effective = configured
    if ollama is not None:
        try:
            effective = ollama.resolve_model(configured)
        except Exception:  # noqa: BLE001
            pass
    return {
        "models": models,
        "current_model": effective,
        "configured_model": configured,
        "model_substituted": effective != configured,
        "engine": getattr(engine, "name", "offline"),
        # Fallback window (used when a model's own window can't be read) and the
        # OPT-IN ceiling (0 = none: every model gets its full window).
        "num_ctx_fallback": settings.ollama_num_ctx,
        "num_ctx_ceiling": settings.ollama_max_num_ctx,
        "num_ctx_floor": settings.ollama_min_num_ctx,
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
    # `private`, not `public`. The signature in the URL is the capability, so a
    # shared proxy caching the response would be storing one user's generated
    # work under a key anyone holding that URL can replay. Browser caching --
    # which is what actually matters for an iframe reloading a 3D scene -- is
    # unaffected.
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "private, max-age=86400"})
