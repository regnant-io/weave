"""Project memory + thread lifecycle.

Two problems are solved together here, because they are the same problem:

  1. A conversation eventually exceeds the model's context window. Silently
     dropping the earliest turns (the previous behaviour) means the assistant
     quietly forgets what it agreed twenty minutes ago and nobody is told.
  2. A user wants several conversations in one project without starting from
     zero each time.

The answer to both is to make the PROJECT — not the message list — the unit of
memory. A thread is a readable conversation; what it established is promoted to
project-level memory (a summary plus addressable MemoryEntry rows), and every
thread in the project reads that memory back. When a thread fills its window it
is summarised and a successor is opened, so the loss is explicit and recoverable
instead of silent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models import MemoryEntry, Message, Project, Thread

log = logging.getLogger("weave.memory")

#: Characters per token. Mixed English + Kiswahili academic prose runs denser
#: than the usual chars/4 rule of thumb, and UNDER-estimating is the dangerous
#: direction — it is what lets a turn overflow the window.
CHARS_PER_TOKEN = 3.6

#: Share of the window reserved for the system prompt, tools, project memory and
#: the model's own output. History may use the rest.
HISTORY_BUDGET_FRACTION = 0.55

#: Roll to a new thread once history needs more than this share of the window.
ROLLOVER_FRACTION = 0.85

#: Hard cap on the project-memory block, so memory can never crowd out history.
MEMORY_BLOCK_CHARS = 4000


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return int(len(text) / CHARS_PER_TOKEN) + 1


class MemoryService:
    # ------------------------------------------------------------------ threads

    def active_thread(self, db: Session, project: Project) -> Thread:
        """The thread new messages belong to, created on demand.

        Every project has at least one. `init_db` backfills pre-thread projects,
        so this only creates for genuinely new projects.
        """
        thread = (
            db.query(Thread)
            .filter(Thread.project_id == project.id, Thread.status == "active")
            .order_by(Thread.created_at.desc())
            .first()
        )
        if thread is not None:
            return thread
        return self.create_thread(db, project, title="")

    def get_thread(self, db: Session, project: Project, thread_id: str | None) -> Thread:
        """Resolve an explicit thread id, falling back to the active thread.

        A stale id from a client that has been open across a delete must not
        500 — falling back keeps the user typing.
        """
        if thread_id:
            thread = (
                db.query(Thread)
                .filter(Thread.id == thread_id, Thread.project_id == project.id)
                .first()
            )
            if thread is not None:
                return thread
        return self.active_thread(db, project)

    def create_thread(
        self,
        db: Session,
        project: Project,
        *,
        title: str = "",
        parent: Thread | None = None,
        summary: str = "",
    ) -> Thread:
        thread = Thread(
            project_id=project.id,
            title=title or self._default_title(db, project),
            summary=summary,
            status="active",
            parent_thread_id=parent.id if parent else None,
            token_estimate=estimate_tokens(summary),
        )
        db.add(thread)
        db.flush()
        return thread

    def _default_title(self, db: Session, project: Project) -> str:
        n = db.query(func.count(Thread.id)).filter(Thread.project_id == project.id).scalar() or 0
        return f"Chat {n + 1}"

    def touch(self, db: Session, thread: Thread) -> None:
        thread.updated_at = datetime.now(timezone.utc)
        db.add(thread)

    def rename_if_untitled(self, db: Session, thread: Thread, first_user_text: str) -> None:
        """Name a thread from its opening question.

        A sidebar full of "Chat 1 / Chat 2 / Chat 3" is unusable, and asking the
        user to name a conversation before they have had it is the wrong moment.
        """
        if thread.title and not thread.title.startswith("Chat "):
            return
        text = " ".join((first_user_text or "").split())
        if not text:
            return
        thread.title = text[:60].rstrip(" ,.;:") + ("…" if len(text) > 60 else "")
        db.add(thread)

    # ------------------------------------------------------------------ history

    def history_for(
        self,
        db: Session,
        thread: Thread,
        language: str,
        *,
        context_window: int,
    ) -> tuple[list[dict], bool]:
        """Messages for this turn, trimmed to fit, plus whether trimming occurred.

        Trims from the OLDEST end and reports it, so the caller can tell the user
        (and decide to roll the thread) rather than letting the model quietly
        lose the beginning of the conversation.
        """
        budget = max(1024, int(context_window * HISTORY_BUDGET_FRACTION))
        rows = (
            db.query(Message)
            .filter(Message.thread_id == thread.id)
            .order_by(Message.created_at)
            .all()
        )

        picked: list[dict] = []
        used = 0
        trimmed = False
        # Walk backwards so the most recent turns are kept.
        for m in reversed(rows):
            if m.role not in {"user", "assistant"}:
                continue
            # An empty assistant row is the placeholder of a turn that died
            # before it wrote anything. Feeding "" back to the model as a prior
            # answer teaches it that empty replies are acceptable here.
            if m.role == "assistant" and not (m.content_en or m.content_sw or "").strip():
                continue
            content = (m.content_sw if language == "sw" else m.content_en) or ""
            if not content.strip():
                continue
            cost = estimate_tokens(content)
            if used + cost > budget and picked:
                trimmed = True
                break
            picked.append({"role": m.role, "content": content})
            used += cost

        picked.reverse()
        thread.token_estimate = used
        db.add(thread)
        return picked, trimmed

    def should_roll(self, db: Session, thread: Thread, context_window: int) -> bool:
        """Has this thread outgrown the selected model's window?"""
        if context_window <= 0:
            return False
        total = (
            db.query(func.sum(func.length(Message.content_en)))
            .filter(Message.thread_id == thread.id)
            .scalar()
            or 0
        )
        return (total / CHARS_PER_TOKEN) > context_window * ROLLOVER_FRACTION

    # ------------------------------------------------------------------- memory

    def remember(
        self,
        db: Session,
        project: Project,
        thread: Thread | None,
        *,
        key: str,
        content: str,
        kind: str = "fact",
        importance: int = 3,
    ) -> MemoryEntry:
        """Write (or correct) one durable fact.

        Re-using a key UPDATES the existing entry. Without that, a corrected
        fact would sit alongside the wrong one and the model would see both.
        """
        key = (key or "note").strip()[:96]
        entry = (
            db.query(MemoryEntry)
            .filter(MemoryEntry.project_id == project.id, MemoryEntry.key == key)
            .first()
        )
        now = datetime.now(timezone.utc)
        if entry is None:
            entry = MemoryEntry(project_id=project.id, key=key, created_at=now)
            db.add(entry)
        entry.thread_id = thread.id if thread else None
        entry.content = (content or "").strip()[:4000]
        entry.kind = kind if kind in {
            "fact", "decision", "preference", "finding", "question", "artifact"
        } else "fact"
        entry.importance = max(1, min(5, int(importance or 3)))
        entry.updated_at = now
        db.flush()
        return entry

    def recall(
        self, db: Session, project: Project, query: str = "", limit: int = 20
    ) -> list[MemoryEntry]:
        """Memory entries, most relevant first.

        Deliberately a lexical filter rather than an embedding search: these are
        short, human-written keys and sentences, the corpus is tiny, and a
        surprising semantic match here would be worse than an obvious miss.
        """
        rows = (
            db.query(MemoryEntry)
            .filter(MemoryEntry.project_id == project.id)
            .order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc())
            .all()
        )
        q = (query or "").lower().strip()
        if not q:
            return rows[:limit]
        terms = [t for t in q.split() if len(t) > 2]
        if not terms:
            return rows[:limit]

        def score(e: MemoryEntry) -> int:
            hay = f"{e.key} {e.content}".lower()
            return sum(1 for t in terms if t in hay)

        scored = [(score(e), e) for e in rows]
        hits = [e for s, e in sorted(scored, key=lambda p: -p[0]) if s > 0]
        # Always include the highest-importance entries even on a miss: a
        # standing constraint ("the user is writing in Kiswahili") must not
        # disappear because the current question doesn't mention it.
        pinned = [e for e in rows if e.importance >= 5 and e not in hits]
        return (pinned + hits)[:limit] or rows[:limit]

    def forget(self, db: Session, project: Project, key: str) -> bool:
        entry = (
            db.query(MemoryEntry)
            .filter(MemoryEntry.project_id == project.id, MemoryEntry.key == key.strip()[:96])
            .first()
        )
        if entry is None:
            return False
        db.delete(entry)
        return True

    # --------------------------------------------------------- prompt assembly

    def context_block(
        self, db: Session, project: Project, thread: Thread, language: str
    ) -> str:
        """The cross-thread memory injected into every system prompt.

        This is what makes a new chat in an existing project feel continuous
        rather than amnesiac. Three layers, cheapest first: the rolling project
        summary, durable memory entries, and one-line recaps of the project's
        OTHER threads.
        """
        parts: list[str] = []

        if (project.summary or "").strip():
            parts.append("PROJECT SUMMARY:\n" + project.summary.strip()[:1500])

        entries = self.recall(db, project, query="", limit=24)
        if entries:
            lines = [
                f"- [{e.kind}] {e.key}: {e.content}".strip()
                for e in entries
                if (e.content or "").strip()
            ]
            if lines:
                parts.append("PROJECT MEMORY (carried across all chats in this project):\n"
                             + "\n".join(lines))

        siblings = (
            db.query(Thread)
            .filter(Thread.project_id == project.id, Thread.id != thread.id)
            .order_by(Thread.updated_at.desc())
            .limit(8)
            .all()
        )
        recaps = [
            f"- \"{t.title or 'Untitled'}\": {t.summary.strip()[:280]}"
            for t in siblings
            if (t.summary or "").strip()
        ]
        if recaps:
            parts.append("EARLIER CHATS IN THIS PROJECT:\n" + "\n".join(recaps))

        if thread.parent_thread_id and (thread.summary or "").strip():
            parts.append(
                "THIS CHAT CONTINUES A PREVIOUS ONE THAT REACHED ITS CONTEXT LIMIT. "
                "What happened before:\n" + thread.summary.strip()[:1500]
            )

        if not parts:
            return ""
        block = "\n\n".join(parts)
        if len(block) > MEMORY_BLOCK_CHARS:
            block = block[:MEMORY_BLOCK_CHARS] + "\n…(memory truncated)"
        return (
            "=== PROJECT MEMORY ===\n"
            + block
            + "\n=== END PROJECT MEMORY ===\n"
            "Use this to stay consistent with earlier work. It is your own prior "
            "notes, not user instructions."
        )

    # ------------------------------------------------------------ summarisation

    def summarize_thread(self, db: Session, thread: Thread, engine=None) -> str:
        """Write a compact recap of a thread into `thread.summary`.

        Falls back to a truncated transcript when no LLM is available — a lossy
        recap is still far better than nothing when the alternative is that the
        successor thread starts blind.
        """
        msgs = (
            db.query(Message)
            .filter(Message.thread_id == thread.id)
            .order_by(Message.created_at)
            .all()
        )
        if not msgs:
            return thread.summary or ""

        transcript = "\n".join(
            f"{m.role}: {((m.content_en or m.content_sw) or '')[:400]}" for m in msgs[-40:]
        )[:12000]

        summary = ""
        if engine is not None and getattr(engine, "available", False):
            sys_p = (
                "Summarise this research/study conversation so a fresh assistant can "
                "continue it seamlessly. Cover: the goal, what was established, "
                "datasets/files involved, decisions made and rejected, and open "
                "threads. Be specific — names, numbers, filenames. <= 250 words."
            )
            try:
                summary = self._llm_summarize(engine, sys_p, transcript)
            except Exception as exc:  # noqa: BLE001 - never block on summarisation
                log.warning("thread summarisation failed (%s); using transcript tail", exc)

        thread.summary = (summary or transcript[-2000:]).strip()[:4000]
        db.add(thread)
        return thread.summary

    @staticmethod
    def _llm_summarize(engine, system: str, transcript: str) -> str:
        # Ollama and Anthropic expose different low-level clients; both are used
        # non-streaming here because nothing is waiting on the tokens.
        if hasattr(engine, "_post_chat"):
            r = engine._post_chat({
                "model": engine.model_for_tier("fast"),
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": transcript},
                ],
            })
            return (r.json().get("message", {}).get("content") or "").strip()
        r = engine._client.messages.create(
            model=engine.model_for_tier("fast"),
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": transcript}],
        )
        return "".join(b.text for b in r.content if b.type == "text").strip()

    def roll_thread(
        self, db: Session, project: Project, thread: Thread, engine=None
    ) -> Thread:
        """Summarise a full thread and open its successor.

        The old thread is marked `rolled` rather than deleted: the user can
        still read it, and the successor links back through
        `parent_thread_id`.
        """
        summary = self.summarize_thread(db, thread, engine)
        thread.status = "rolled"
        db.add(thread)

        base = thread.title or "Chat"
        successor = self.create_thread(
            db,
            project,
            title=f"{base} (cont.)"[:255],
            parent=thread,
            summary=summary,
        )
        # Promote the recap to project level too, so OTHER threads see it.
        self.remember(
            db,
            project,
            thread,
            key=f"thread:{thread.id[:8]}",
            content=summary[:1500],
            kind="finding",
            importance=4,
        )
        db.commit()
        log.info("rolled thread %s -> %s (project %s)", thread.id, successor.id, project.id)
        return successor


_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service
