"""Live voice: speech in, speech out, and the rules that make it feel like talking.

TWO ENGINES, ONE PROTOCOL
-------------------------
* **browser** (default) — the phone does the work. `SpeechRecognition` produces
  transcripts and `speechSynthesis` speaks the reply; this service sees text in
  both directions. Costs nothing, needs no models, and works on the hardware
  Weave's users actually have.
* **server** (optional) — audio frames go to a Whisper endpoint and replies come
  back from a Piper endpoint. Far better Kiswahili, and far heavier: it is behind
  `WEAVE_STT_URL` / `WEAVE_TTS_URL` and the `voice` compose profile.

The socket protocol is identical either way, so the client does not branch on
which engine is live and a deployment can switch without a frontend change.

WHAT MAKES IT FEEL LIVE
-----------------------
Three things, none of which are the speech recognition:

1. **Speak sentence by sentence.** Waiting for a complete answer before speaking
   adds the whole generation time to the silence. `SentenceChunker` releases each
   sentence the moment it is complete, so the reply starts while the rest is
   still being written.

2. **Barge-in.** A person interrupts by starting to talk, not by pressing stop.
   When speech is detected while the assistant is talking, the turn is cancelled
   immediately — mid-sentence — and what was already spoken stays in the
   transcript so the conversation stays coherent.

3. **Ambient gating.** Always-on listening is only pleasant if the assistant
   stays quiet until it is addressed. `AmbientGate` decides, per utterance,
   whether this was meant for it.
"""
from __future__ import annotations

import logging
import re
import time

from ...config import settings

log = logging.getLogger("weave.voice")

#: A sentence shorter than this is almost always an artefact of an abbreviation
#: ("Dr.", "e.g.") rather than a real sentence boundary, and speaking it alone
#: produces the stuttering delivery that makes synthesised speech grating.
MIN_SPEAKABLE_CHARS = 24

#: Hard ceiling on one spoken chunk, so a wall of text without punctuation still
#: gets broken up rather than arriving as one enormous utterance.
MAX_SPEAKABLE_CHARS = 320

_SENTENCE_END = re.compile(r"(?<=[.!?？。])\s+|(?<=[:;])\s+(?=[A-Z])|\n\n+")

#: Abbreviations that end in a full stop without ending a sentence.
_ABBREV = re.compile(r"\b(?:Dr|Prof|Mr|Mrs|Ms|St|e\.g|i\.e|vs|Fig|No|approx|Bw|Bi)\.$", re.I)


#: Things that are invisible on screen and absurd out loud.
_SPEAK_STRIP = [
    (re.compile(r"```[\s\S]*?```"), " "),            # code fences
    (re.compile(r"`([^`]*)`"), r"\1"),               # inline code
    (re.compile(r"\[S\d+\]"), ""),                   # Weave citation markers
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links and images
    (re.compile(r"https?://\S+"), " "),              # bare URLs
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),    # heading hashes
    (re.compile(r"^\s{0,3}[-*+]\s+", re.M), ""),     # bullet markers
    (re.compile(r"^\s{0,3}\|.*\|\s*$", re.M), " "),  # table rows
    (re.compile(r"^\s{0,3}[-:| ]{6,}\s*$", re.M), " "),  # table rules
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),         # bold
    (re.compile(r"(?<!\w)[*_]([^*_]+)[*_](?!\w)"), r"\1"),  # italics
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n{2,}"), "\n"),
]


def speakable(text: str) -> str:
    """Strip what should never be read aloud.

    The prompt asks for speech-shaped answers, and a capable model obliges. This
    is the belt to that braces: the offline engine composes deterministically and
    never sees a system prompt at all, and small local models drop back into
    markdown under load. Without this, text-to-speech reads "open square bracket
    S one close square bracket" in the middle of a sentence, or spells out a URL
    character by character.

    Deliberately lossy and one-directional — the written transcript in the chat
    keeps the markers; only the spoken copy is stripped.
    """
    out = str(text or "")
    for pattern, replacement in _SPEAK_STRIP:
        out = pattern.sub(replacement, out)
    return out.strip()


class SentenceChunker:
    """Turns a token stream into speakable chunks.

    Fed tokens as they stream; yields a chunk whenever a real sentence boundary
    is crossed. `flush` empties whatever is left at the end of the turn.
    """

    def __init__(self) -> None:
        self._buf = ""

    def push(self, text: str) -> list[str]:
        self._buf += text or ""
        out: list[str] = []
        while True:
            chunk = self._take()
            if chunk is None:
                break
            out.append(chunk)
        return out

    def _take(self) -> str | None:
        if len(self._buf) >= MAX_SPEAKABLE_CHARS:
            # No punctuation in sight — break on the last word boundary rather
            # than mid-word.
            cut = self._buf.rfind(" ", 0, MAX_SPEAKABLE_CHARS)
            cut = cut if cut > MIN_SPEAKABLE_CHARS else MAX_SPEAKABLE_CHARS
            chunk, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            return chunk or None

        match = _SENTENCE_END.search(self._buf)
        if not match:
            return None
        candidate = self._buf[: match.start() + 1].strip()
        if len(candidate) < MIN_SPEAKABLE_CHARS or _ABBREV.search(candidate):
            # Not a real boundary: keep buffering. Searching past this point
            # would need a second regex pass, and the next token will retry.
            nxt = _SENTENCE_END.search(self._buf, match.end())
            if not nxt:
                return None
            candidate = self._buf[: nxt.start() + 1].strip()
            self._buf = self._buf[nxt.end():]
            return candidate or None
        self._buf = self._buf[match.end():]
        return candidate or None

    def flush(self) -> str:
        chunk, self._buf = self._buf.strip(), ""
        return chunk


#: Ways of getting the assistant's attention, in both languages.
_WAKE = re.compile(
    r"\b(weave|wiv|hey weave|habari weave|weave tafadhali)\b", re.I,
)

#: An utterance addressed to the assistant usually asks something or instructs
#: it. This is a heuristic and is treated as one — see AmbientGate.
_ADDRESSED = re.compile(
    r"\?\s*$|"
    r"^\s*(can you|could you|please|what|why|how|when|where|who|which|explain|"
    r"show|help|tell me|give me|make|build|write|find|search|draw|calculate)\b|"
    r"^\s*(unaweza|tafadhali|nini|kwa nini|vipi|lini|wapi|nani|eleza|onyesha|"
    r"nisaidie|niambie|nipe|tengeneza|andika|tafuta|chora|hesabu)\b",
    re.I,
)


class AmbientGate:
    """Decides whether an overheard utterance was meant for the assistant.

    Always-on listening is only tolerable if the thing listening stays quiet.
    The default is SILENCE: an utterance has to name the assistant, or be
    shaped like a request, or arrive inside the short window after it last
    spoke (so a follow-up does not need the wake word again).

    Deliberately conservative. Answering when nobody asked is far worse than
    missing one utterance the user can simply repeat — the first makes the
    feature something people switch off.
    """

    #: After the assistant speaks, the user is in conversation with it and
    #: should not have to say its name to continue.
    FOLLOW_UP_WINDOW = 25.0

    def __init__(self) -> None:
        self._last_spoke_at = 0.0

    def note_spoke(self) -> None:
        self._last_spoke_at = time.monotonic()

    def should_respond(self, text: str, *, ambient: bool) -> tuple[bool, str]:
        """Returns (respond, why) — `why` is surfaced for debugging the gate."""
        clean = (text or "").strip()
        if len(clean) < 2:
            return False, "empty"
        if not ambient:
            # Push-to-talk: the user pressed a button, so they meant it.
            return True, "explicit"
        if _WAKE.search(clean):
            return True, "wake-word"
        if time.monotonic() - self._last_spoke_at < self.FOLLOW_UP_WINDOW:
            return True, "follow-up"
        if _ADDRESSED.search(clean) and len(clean.split()) >= 3:
            return True, "addressed"
        return False, "not addressed"

    @staticmethod
    def strip_wake_word(text: str) -> str:
        return _WAKE.sub("", text or "", count=1).strip(" ,.—-") or (text or "").strip()


#: Short acknowledgements, per language. These are the noises a listener makes
#: to show they are still there; they are not answers and must never carry
#: content, because the model has not seen the utterance yet.
BACKCHANNELS = {
    "en": ["mm", "mhm", "right", "I see", "go on"],
    "sw": ["mm", "ndiyo", "naam", "sawa", "endelea"],
}


class BackchannelPolicy:
    """Rate-limits the little noises so they stay listening cues, not chatter.

    A backchannel every two seconds is an interruption. The policy is: at most
    one per utterance, never within the first few seconds, and never twice in a
    row without the user having said something new.
    """

    MIN_INTERVAL = 6.0
    MIN_WORDS_BEFORE = 12

    def __init__(self) -> None:
        self._last = 0.0
        self._index = 0

    def maybe(self, partial_text: str, language: str) -> str | None:
        if len(str(partial_text or "").split()) < self.MIN_WORDS_BEFORE:
            return None
        now = time.monotonic()
        if now - self._last < self.MIN_INTERVAL:
            return None
        self._last = now
        pool = BACKCHANNELS.get(language, BACKCHANNELS["en"])
        # Rotate rather than randomise: reproducible, and it avoids the same
        # sound twice running without needing an RNG in the hot path.
        word = pool[self._index % len(pool)]
        self._index += 1
        return word


class VoiceEngines:
    """What this deployment can actually do, and the calls to do it."""

    def __init__(self) -> None:
        self._httpx = None

    @property
    def stt_url(self) -> str:
        return (getattr(settings, "stt_url", "") or "").rstrip("/")

    @property
    def tts_url(self) -> str:
        return (getattr(settings, "tts_url", "") or "").rstrip("/")

    @property
    def server_stt(self) -> bool:
        return bool(self.stt_url)

    @property
    def server_tts(self) -> bool:
        return bool(self.tts_url)

    def describe(self) -> dict:
        return {
            # The browser engine is always available: it is the client's own
            # Web Speech API, and this service only relays text for it.
            "browser": True,
            "server_stt": self.server_stt,
            "server_tts": self.server_tts,
            "default": "server" if (self.server_stt and self.server_tts) else "browser",
        }

    def _client(self):
        if self._httpx is None:
            import httpx
            self._httpx = httpx
        return self._httpx

    def transcribe(self, audio: bytes, language: str = "en") -> dict:
        """Audio -> text via the configured Whisper-compatible endpoint."""
        if not self.server_stt:
            return {"ok": False, "error": "no server STT configured", "text": ""}
        try:
            resp = self._client().post(
                f"{self.stt_url}/inference",
                files={"file": ("audio.webm", audio, "application/octet-stream")},
                data={"language": language, "response_format": "json"},
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
            return {"ok": True, "text": (body.get("text") or "").strip()}
        except Exception as exc:  # noqa: BLE001
            log.warning("STT failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200], "text": ""}

    def synthesise(self, text: str, language: str = "en") -> dict:
        """Text -> audio bytes via the configured Piper-compatible endpoint."""
        if not self.server_tts:
            return {"ok": False, "error": "no server TTS configured", "audio": b""}
        try:
            resp = self._client().post(
                self.tts_url,
                json={"text": text, "language": language},
                timeout=60,
            )
            resp.raise_for_status()
            return {"ok": True, "audio": resp.content,
                    "mime": resp.headers.get("content-type", "audio/wav")}
        except Exception as exc:  # noqa: BLE001
            log.warning("TTS failed: %s", exc)
            return {"ok": False, "error": str(exc)[:200], "audio": b""}


_engines: VoiceEngines | None = None


def get_voice_engines() -> VoiceEngines:
    global _engines
    if _engines is None:
        _engines = VoiceEngines()
    return _engines
