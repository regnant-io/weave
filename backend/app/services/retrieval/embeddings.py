"""Embedding function.

architecture.md section 7.2 calls for a *multilingual* embedding model evaluated
explicitly on Swahili academic text. Downloading and serving such a model is an
operational decision (Open Decision #2, section 14) and not something to bake into
a zero-service dev boot. So this module ships a deterministic, dependency-free
embedding — a hashed character/word n-gram projection — that is:

  * fully offline and reproducible (same text -> same vector, always)
  * language-agnostic (works on Swahili and English tokens identically)
  * good enough to make hybrid retrieval demonstrably function end-to-end

To swap in a real model, implement `embed_texts` to call your embedding
endpoint (e.g. a multilingual-e5 / BGE-m3 server) and keep the signature. The
retrieval math downstream is identical.
"""
from __future__ import annotations

import hashlib
import math
import re

from ...config import settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _feature_hashes(text: str) -> list[tuple[int, float]]:
    """Return (dim_index, weight) features from unigrams, bigrams and char 3-grams."""
    toks = _tokens(text)
    feats: dict[int, float] = {}

    def bump(token: str, weight: float) -> None:
        h = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        idx = h % settings.embedding_dim
        sign = 1.0 if (h >> 63) & 1 else -1.0
        feats[idx] = feats.get(idx, 0.0) + sign * weight

    for t in toks:
        bump(t, 1.0)
    for a, b in zip(toks, toks[1:]):
        bump(f"{a}_{b}", 0.7)
    # character 3-grams capture Swahili morphology / shared roots
    joined = " ".join(toks)
    for i in range(len(joined) - 2):
        bump(joined[i:i + 3], 0.3)
    return list(feats.items())


# --- Ollama embedding backend (opt-in) --------------------------------------
# Decided ONCE per process so a whole ingest+query run uses one embedding space
# (mixing dims across chunks would silently break cosine similarity).
_ollama_state: dict = {"resolved": False, "active": False, "client": None}


def _resolve_ollama_embeddings() -> bool:
    if _ollama_state["resolved"]:
        return _ollama_state["active"]
    _ollama_state["resolved"] = True
    if not settings.ollama_use_embeddings:
        _ollama_state["active"] = False
        return False
    try:
        import httpx
        client = httpx.Client(
            base_url=settings.ollama_host.rstrip("/"), timeout=30.0,
            headers={"ngrok-skip-browser-warning": "true", "User-Agent": "weave/1.0"},
        )
        # probe: embed a token and confirm we get a vector back
        probe = _ollama_embed_raw(client, "weave")
        if probe:
            _ollama_state["client"] = client
            _ollama_state["active"] = True
            return True
    except Exception:  # noqa: BLE001 - unreachable / model not pulled
        pass
    _ollama_state["active"] = False
    return False


def _ollama_embed_raw(client, text: str) -> list[float] | None:
    # Newer Ollama exposes /api/embed ({input} -> {embeddings:[[...]]}); older
    # exposes /api/embeddings ({prompt} -> {embedding:[...]}). Try both.
    try:
        r = client.post("/api/embed", json={"model": settings.ollama_embed_model, "input": text})
        if r.status_code == 200:
            embs = r.json().get("embeddings")
            if embs and embs[0]:
                return [float(x) for x in embs[0]]
    except Exception:  # noqa: BLE001
        pass
    r = client.post("/api/embeddings", json={"model": settings.ollama_embed_model, "prompt": text})
    r.raise_for_status()
    emb = r.json().get("embedding")
    return [float(x) for x in emb] if emb else None


def embedding_backend() -> str:
    """Reported by /health."""
    return "ollama" if _resolve_ollama_embeddings() else "deterministic"


def _deterministic_embed(text: str) -> list[float]:
    vec = [0.0] * settings.embedding_dim
    for idx, w in _feature_hashes(text):
        vec[idx] += w
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def embed_text(text: str) -> list[float]:
    if _resolve_ollama_embeddings():
        try:
            vec = _ollama_embed_raw(_ollama_state["client"], text)
            if vec:
                norm = math.sqrt(sum(v * v for v in vec))
                return [v / norm for v in vec] if norm > 0 else vec
        except Exception:  # noqa: BLE001 - fall back for this call
            pass
    return _deterministic_embed(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [embed_text(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # both are L2-normalised, so dot == cosine
