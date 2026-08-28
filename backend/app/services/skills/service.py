"""The skill library.

A skill is a worked procedure for a task that is easy to get wrong and expensive
to get wrong twice — running a regression correctly, screening a literature
search, designing a visualisation that reads as deliberate rather than default.

WHY SKILLS RATHER THAN A BIGGER SYSTEM PROMPT
---------------------------------------------
Everything in this library could in principle be pasted into the system prompt.
It must not be. The prompt is paid for on EVERY turn, by every model, including
the 3B one running on a laptop in Dodoma; a library of twenty procedures would
crowd out the conversation itself and make the small models measurably worse.
Skills are paid for only when they are needed, by a model that has decided it
needs them.

The two-step shape — `list_skills` to see what exists, `read_skill` to load one —
is deliberate and is enforced socially rather than technically: a name tells you
almost nothing, so the assistant is instructed to read a skill before claiming to
follow it. Listing is cheap (names and one-line descriptions); reading costs real
tokens and happens once, for the one skill that applies.

Skills are plain Markdown with a small YAML-ish front matter block. They live in
`library/` as files rather than rows in a table so they are reviewable in a diff,
which is the only way a procedure like "how to choose a statistical test" stays
correct over time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LIBRARY = Path(__file__).parent / "library"

#: Skills longer than this are almost certainly trying to be documentation. The
#: cap is a design constraint, not a safety limit: a procedure that cannot be
#: stated in a few thousand characters has not been thought through, and it will
#: not survive contact with a small model's context window.
MAX_SKILL_CHARS = 14_000


@dataclass(frozen=True)
class Skill:
    name: str
    title: str
    description: str
    #: Free-text topic tags used only to make `list_skills(query=...)` useful.
    tags: tuple[str, ...]
    body: str

    def summary(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "chars": len(self.body),
        }


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _parse(path: Path) -> Skill | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta: dict[str, str] = {}
    body = raw
    match = _FRONT_MATTER.match(raw)
    if match:
        body = raw[match.end():]
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")

    name = meta.get("name") or path.stem
    title = meta.get("title") or name.replace("-", " ").capitalize()
    description = meta.get("description") or ""
    tags = tuple(t.strip() for t in meta.get("tags", "").split(",") if t.strip())
    return Skill(name=name, title=title, description=description, tags=tags,
                 body=body.strip())


@lru_cache(maxsize=1)
def _load_all() -> dict[str, Skill]:
    """Read the library once per process.

    Skills are static files shipped with the image, so caching is safe and the
    alternative — re-reading twenty files on every `list_skills` call — is pure
    waste on a box that is also running a model.
    """
    out: dict[str, Skill] = {}
    if not LIBRARY.is_dir():
        return out
    for path in sorted(LIBRARY.glob("*.md")):
        skill = _parse(path)
        if skill:
            out[skill.name] = skill
    return out


class SkillService:
    @property
    def enabled(self) -> bool:
        return bool(_load_all())

    def list(self, query: str = "", limit: int = 40) -> list[dict]:
        """Names and one-liners. Never bodies — that is what `read` is for."""
        skills = list(_load_all().values())
        q = (query or "").strip().lower()
        if q:
            terms = [t for t in re.split(r"\W+", q) if len(t) > 2]

            def score(s: Skill) -> int:
                hay = f"{s.name} {s.title} {s.description} {' '.join(s.tags)}".lower()
                return sum(1 for t in terms if t in hay)

            scored = [(score(s), s) for s in skills]
            skills = [s for n, s in sorted(scored, key=lambda p: -p[0]) if n > 0] or skills
        return [s.summary() for s in skills[:limit]]

    @staticmethod
    def _normalise(name: str) -> str:
        # Skill names are hyphenated; models type them with spaces or
        # underscores about as often. Normalising here costs nothing and saves a
        # wasted tool call plus a confused retry.
        return re.sub(r"[\s_]+", "-", (name or "").strip().lower())

    def read(self, name: str) -> Skill | None:
        skills = _load_all()
        key = self._normalise(name)
        if not key:
            return None
        if key in skills:
            return skills[key]
        # Tolerate the obvious near-misses ("data analysis" for
        # "data-analysis-workflow") rather than making the model guess twice.
        for skill_name, skill in skills.items():
            if key in skill_name or skill_name in key:
                return skill
        return None

    def names(self) -> list[str]:
        return list(_load_all().keys())


_service: SkillService | None = None


def get_skills() -> SkillService:
    global _service
    if _service is None:
        _service = SkillService()
    return _service
