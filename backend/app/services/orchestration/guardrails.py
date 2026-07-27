"""Product-specific guardrails (architecture 6.5).

  1. Academic-integrity guard (student mode): detect "do my assignment for me"
     requests and force a Socratic/coaching framing regardless of phrasing.
  2. Hallucination guard for local facts: post-hoc check that statistic/law/
     curriculum/institution claims trace to a retrieved passage; if grounding was
     empty, require an explicit "not grounded" acknowledgement.
  3. Predatory-journal flag: handled at retrieval + citations layer, surfaced here.
"""
from __future__ import annotations

import re

_INTEGRITY_PATTERNS = [
    # English: write/do my essay/assignment...
    r"\b(write|draft|complete|finish|do)\b.{0,40}\b"
    r"(my|the)?\s?(essay|assignment|homework|coursework|answer|report)\b",
    r"\bdo my (assignment|homework|essay|coursework)\b",
    # Swahili: match the 'andik-' write stem in any conjugation (andika, niandikie,
    # uniandikie), plus fanyie/tengenez, near a work noun. This is what the eval
    # harness surfaced: 'niandikie insha' was previously missed.
    r"\b\w*andik\w*\b.{0,40}\b(insha|kazi|zoezi|jibu|ripoti|assignment)\b",
    r"\b(nifanyie|unifanyie|nitengenezee|unitengenezee)\b.{0,40}\b(kazi|zoezi|insha|jibu)\b",
    r"\bni(andik|fany|tengenez)\w*\b",
]
_INTEGRITY_RE = re.compile("|".join(_INTEGRITY_PATTERNS), re.I | re.S)

# Signals that the answer is asserting a local empirical fact.
_LOCAL_FACT_RE = re.compile(
    r"(\b\d{1,3}(?:[.,]\d+)?\s?%|\bpercent\b|asilimia|\bGDP\b|Pato la Taifa|"
    r"population of|idadi ya watu|\bNBS\b|\bNECTA\b|according to the (law|act)|"
    r"sheria ya|kifungu cha)", re.I,
)


def triggers_integrity_guard(user_text: str, mode: str) -> bool:
    if mode != "student":
        return False
    return bool(_INTEGRITY_RE.search(user_text))


def integrity_redirect_instruction(language: str) -> str:
    if language == "sw":
        return (
            "MAELEZO YA UADILIFU WA KITAALUMA: Mwanafunzi ameomba uandike kazi yake. "
            "USIANDIKE insha/zoezi kwa niaba yake. Badala yake, msaidie kupanga muundo, "
            "kuelewa hoja, na kuandika mwenyewe hatua kwa hatua."
        )
    return (
        "ACADEMIC INTEGRITY NOTICE: the student asked you to write their work. Do NOT "
        "write the essay/assignment for them. Instead, coach them: help outline, "
        "understand, and draft it themselves, step by step."
    )


import re as _re

_CLAIM_SIGNAL = _re.compile(
    r"(\d{1,4}(?:[.,]\d+)?\s?%|\basilimia\b|\bpercent\b|\b\d{4}\b|\bGDP\b|Pato la Taifa|"
    r"\bmillion\b|\bbillion\b|milioni|bilioni|according to|kulingana na|\bNBS\b|\bNECTA\b|"
    r"\bWHO\b|\bUNESCO\b|census|sensa)", _re.I,
)
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "was", "are", "which",
         "kwa", "ya", "na", "wa", "ni", "za", "la", "katika", "cha"}


def _key_terms(text: str) -> set[str]:
    return {w for w in _re.findall(r"\w+", text.lower()) if len(w) > 3 and w not in _STOP}


def check_grounding(answer_text: str, had_passages: bool,
                    passages: list | None = None) -> tuple[bool, str]:
    """Post-hoc hallucination guard v2 (architecture 6.5).

    - No passages + a local-fact assertion  -> flag (unverified).
    - Passages present: for each sentence that makes a *specific empirical claim*
      (a statistic, year, named body, 'according to'), require lexical overlap with
      at least one retrieved passage. Sentences that don't overlap any source are
      surfaced as potentially-unsupported.
    """
    answer_text = answer_text or ""
    if not had_passages:
        if _LOCAL_FACT_RE.search(answer_text):
            return False, ("This answer states a local statistic/law/curriculum fact but no "
                           "grounding source was retrieved. Treat it as unverified.")
        return True, ""

    passage_terms: list[set[str]] = [_key_terms(p.get("content", "")) for p in (passages or [])]
    if not passage_terms:
        return True, ""

    unsupported = []
    for sentence in _re.split(r"(?<=[.!?])\s+", answer_text):
        if not _CLAIM_SIGNAL.search(sentence):
            continue
        terms = _key_terms(sentence)
        if not terms:
            continue
        overlap = any(len(terms & pt) >= 2 for pt in passage_terms)
        if not overlap:
            unsupported.append(sentence.strip()[:160])

    if unsupported:
        note = ("Some empirical claims may not be fully supported by the retrieved sources: "
                + " | ".join(unsupported[:2]))
        return False, note
    return True, ""
