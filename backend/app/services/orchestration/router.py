"""Model-tiering router (architecture 6.4).

A cheap classification step decides which tier handles a turn:
  * fast tier    -> intent classification, simple factual Q&A, micro-interactions
  * frontier tier-> Socratic teaching, code generation, literature synthesis,
                    anything producing citable/gradeable output

The classifier itself is intentionally lightweight (keyword + structure heuristics)
so it never costs a frontier call just to route. A production build may replace it
with a fast-tier LLM call; the interface is the same.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DATA_SIGNALS = re.compile(
    r"\b(mean|median|average|wastani|regression|correlation|uhusiano|distribution|"
    r"test|chart|graph|grafu|plot|column|safu|dataset|takwimu|significant|p-value|"
    r"histogram|scatter|trend|mwenendo|analy[sz]e|changanua)\b", re.I,
)
LITERATURE_SIGNALS = re.compile(
    r"\b(cite|citation|rejea|reference|source|chanzo|literature|utafiti|study|"
    r"paper|journal|jarida|according to|kulingana na|NBS|COSTECH|UDSM)\b", re.I,
)
CONCEPT_SIGNALS = re.compile(
    r"\b(what is|explain|eleza|nini maana|define|fafanua|why|kwa nini|how does|"
    r"vipi|help me understand|nisaidie kuelewa)\b", re.I,
)


@dataclass
class RouteDecision:
    intent: str          # data | literature | concept | general
    tier: str            # fast | frontier
    needs_retrieval: bool
    needs_sandbox: bool


def classify(text: str, mode: str) -> RouteDecision:
    is_data = bool(DATA_SIGNALS.search(text))
    is_lit = bool(LITERATURE_SIGNALS.search(text))
    is_concept = bool(CONCEPT_SIGNALS.search(text))

    if is_data:
        intent = "data"
    elif is_lit:
        intent = "literature"
    elif is_concept:
        intent = "concept"
    else:
        intent = "general"

    # Frontier tier for the moments that matter (teaching, code, synthesis).
    frontier = (
        intent in {"data", "literature"}
        or (mode == "student" and intent == "concept")
        or len(text) > 400
    )
    return RouteDecision(
        intent=intent,
        tier="frontier" if frontier else "fast",
        needs_retrieval=is_lit or is_concept,
        needs_sandbox=is_data,
    )
