"""Citation / predatory-journal checking (architecture 6.5, 5.2 /citations/check).

Cross-references a citation against a known-predatory list (Beall's-list-derived
and community-updated) before a researcher is allowed to cite it uncritically.
The list here is a representative seed; production loads and refreshes the full
community lists on a schedule.
"""
from __future__ import annotations

import re

# Representative seed of predatory-publisher name fragments (Beall's-list-derived).
# NOT exhaustive — a deployment refreshes this from maintained community lists.
PREDATORY_FRAGMENTS = {
    "omics", "scirp", "scientific research publishing", "academic journals inc",
    "science publishing group", "internationalscholarsjournals", "iiste",
    "world academy of science", "waset", "bentham open", "ashdin",
    "david publishing", "hikari", "lambert academic",
}


def check_reference(reference: str) -> tuple[bool, str]:
    """Return (flagged_predatory, reason)."""
    text = reference.lower()
    hits = [frag for frag in PREDATORY_FRAGMENTS if frag in text]
    if hits:
        return True, (
            "Matches a known predatory-publisher pattern "
            f"({', '.join(sorted(hits))}). Verify the venue before citing."
        )
    # heuristic: obvious "fast/guaranteed publication" spam language
    if re.search(r"\b(guaranteed|rapid|fast[- ]track)\b.*\bpublication\b", text):
        return True, "Language matches predatory 'guaranteed/rapid publication' solicitation."
    return False, "No predatory-journal signals detected in the provided reference."
