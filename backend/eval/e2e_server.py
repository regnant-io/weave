"""Throwaway offline API used only by Playwright release journeys."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="weave_e2e_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["WEAVE_DATABASE_URL"] = f"sqlite:///{(root / 'e2e.db').as_posix()}"
os.environ["WEAVE_STORAGE_LOCAL_DIR"] = str(root / "storage")
os.environ["WEAVE_FORCE_OFFLINE_LLM"] = "true"
os.environ["WEAVE_LLM_BACKEND"] = "offline"
os.environ["WEAVE_SECRET_KEY"] = "e2e-only-secret-key-with-sufficient-length"
os.environ["WEAVE_DEBUG"] = "true"
os.environ["WEAVE_REDIS_URL"] = ""
# Browser projects share loopback as a client address. Keep the journey suite
# from testing aggregate test-runner concurrency instead of the UI flow; the
# limiter algorithm and production value have direct backend tests.
os.environ["WEAVE_RATE_LIMIT_AUTH_PER_MIN"] = "100"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, log_level="warning")
