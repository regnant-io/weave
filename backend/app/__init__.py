"""Weave backend — bilingual study + research platform.

Package layout mirrors architecture.md section 5.1 (service boundaries):

    app.api                 -> Gateway (auth, validation, rate limiting, routing)
    app.services.orchestration -> Orchestration Service (LLM, modes, bilingual)
    app.services.retrieval  -> Retrieval Service (hybrid RAG over TZ sources)
    app.services.analysis   -> Analysis Service (datasets)
    app.services.sandbox    -> Sandbox Manager (untrusted code execution)
"""

__version__ = "1.0.0"
