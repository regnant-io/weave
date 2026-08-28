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

# These patterns must match "write my assignment for me" and NOT "draft the
# report", "write the introduction with me", or "help me write this up".
#
# The previous set was far too broad and was a significant cause of the
# assistant refusing ordinary work: `(write|draft|complete|finish|do).{0,40}
# (my|the)?\s?(essay|assignment|homework|coursework|answer|report)` matches
# "draft the report" and even "do the answer", and the bare Swahili stem
# `\bni(andik|fany|tengenez)\w*\b` matched any first-person request to write,
# make or produce ANYTHING — including "nitengenezee grafu" (make me a graph),
# which is not an integrity question at all.
#
# The guard now requires possession of schoolwork specifically ("MY essay",
# "insha YANGU"), so a request to draft, edit or co-write is left alone.
_INTEGRITY_PATTERNS = [
    # English: write/do MY essay|assignment|homework|coursework|dissertation.
    r"\b(write|do|complete|finish|submit)\b[^.?!]{0,30}\bmy\b[^.?!]{0,20}\b"
    r"(essay|assignment|homework|coursework|dissertation|thesis|term\s?paper)\b",
    # "write it for me" / "do this for me" attached to schoolwork.
    r"\b(essay|assignment|homework|coursework)\b[^.?!]{0,40}\bfor me\b",
    r"\bfor me to (submit|hand in|turn in)\b",
    # Swahili: a write/make stem (andik-, tengenez-, fany-) near a piece of
    # SCHOOLWORK carrying a possessive ('yangu'/'langu'/'zangu'). The possessive
    # is what separates "make me my exercise" from "nitengenezee grafu ya mvua"
    # (make me a rainfall graph), which is ordinary work and must not trigger.
    r"\b\w*(andik|tengenez|fany)\w*\b[^.?!]{0,40}"
    r"\b(insha|zoezi|kazi ya (shule|darasa)|tasnifu)\b"
    r"[^.?!]{0,20}\b(yangu|langu|zangu|yetu)\b",
    r"\b(niwasilishe|kuwasilisha)\b[^.?!]{0,30}\b(insha|zoezi|kazi)\b",
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
    """Steer towards co-writing — not a refusal.

    The old text was a flat "do NOT write it", which produced an assistant that
    argued with the student about the request instead of helping with the work.
    Writing WITH them achieves the same end (the understanding transfers, the
    submitted argument is theirs) without a standoff, and it is far more likely
    to actually be followed than a prohibition the student can rephrase around.
    """
    if language == "sw":
        return (
            "UADILIFU WA KITAALUMA: mwanafunzi ameomba umwandikie kazi yake ya shule. "
            "Andika NAYE, si KWA NIABA yake: jengeni muhtasari pamoja, andika sehemu "
            "moja baada ya nyingine, na kila hatua mwombe atoe hoja, ushahidi na "
            "hitimisho lake mwenyewe. Eleza sababu ya kila chaguo ili aelewe. Sema "
            "MARA MOJA tu, kwa ufupi, kwamba kazi anayowasilisha inapaswa kuwa yake — "
            "kisha endelea kumsaidia. Usikatae kujadili mada."
        )
    return (
        "ACADEMIC INTEGRITY: the student asked you to write their schoolwork. Write "
        "WITH them, not FOR them: build the outline together, draft it section by "
        "section, and at each step ask them to supply their own argument, evidence "
        "and conclusion. Explain the reasoning behind every choice so the "
        "understanding transfers. Say ONCE, briefly, that the work they submit needs "
        "to be theirs — then get on with helping. Do not refuse to engage with the "
        "topic and do not lecture."
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
