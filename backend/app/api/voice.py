"""The live session socket: voice, barge-in, ambient presence, screen sharing.

ONE SOCKET, NOT FOUR
--------------------
Voice and screen sharing are the same conversation. A user saying "what's wrong
with this?" while sharing their screen is one utterance whose meaning depends on
the frame that arrived a second earlier, and splitting them across two transports
would mean reassembling that ordering by timestamp — which is exactly the kind of
thing that works in testing and fails on a slow connection.

PROTOCOL (JSON text frames)

  client -> server
    hello        {engine, language, ambient, mode}
    transcript   {text, final}          browser STT result
    audio        {data:b64, mime}       server STT path
    barge_in     {}                     user started talking over the assistant
    frame        {data:b64, at}         screen-share still
    screen_stop  {}
    say_done     {}                     client finished speaking a chunk
    bye          {}

  server -> client
    ready        {engines, session_id}
    heard        {text, responding, why}
    backchannel  {text}
    turn_start   {turn_id}
    say          {text, seq}            speak this (browser TTS)
    audio        {data:b64, mime, seq}  speak this (server TTS)
    step         {tool, title}          tool activity, so the UI can show work
    turn_end     {text, turn_id}
    interrupted  {}
    screen_noted {accepted, reason}
    error        {message}

WHY THE TURN RUNS IN A THREAD
-----------------------------
`Orchestrator.stream_turn` is a synchronous generator that blocks on model I/O.
Driving it from the event loop would stall every other socket on the process, so
it runs on a worker thread and pushes events back through
`loop.call_soon_threadsafe`. That is also what makes barge-in work: the cancel
Event is set from the loop while the worker is mid-generation.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import threading
import time
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..deps import get_current_user
from ..models import Project, User
from ..security import decode_ws_ticket
from ..services.voice import (AmbientGate, BackchannelPolicy, SentenceChunker,
                              get_voice_engines, speakable)

log = logging.getLogger("weave.voice.api")
router = APIRouter()

#: Screen frames the assistant may hold at once. Only the most recent matters
#: for "what am I looking at", and keeping a reel would blow up the turn.
SCREEN_BUFFER = 3

#: Ignore frames arriving faster than this. The client is told to send on change,
#: but a client that ignores that must not be able to flood the socket.
MIN_FRAME_INTERVAL = 1.0


@router.post("/ws-ticket")
def ws_ticket(user: User = Depends(get_current_user)) -> dict:
    """Mint a single-use-shaped, sixty-second credential for opening a socket.

    POST rather than GET so it is never cached, prefetched, or logged as a
    bookmarkable URL. See `security.create_ws_ticket` for why sockets do not
    simply reuse the session token.
    """
    from ..security import WS_TICKET_TTL_SECONDS, create_ws_ticket

    return {"token": create_ws_ticket(user.id), "expires_in": WS_TICKET_TTL_SECONDS}


@router.get("/voice/config")
def voice_config(_user: User = Depends(get_current_user)) -> dict:
    """What this deployment can do, so the client picks an engine it can use."""
    engines = get_voice_engines().describe()
    return {
        "engines": engines,
        "ambient_available": True,
        "screen_share_available": True,
        "backchannel_available": True,
    }


class LiveSession:
    """One user's live session over one socket."""

    def __init__(self, websocket: WebSocket, user_id: str, project_id: str,
                 loop: asyncio.AbstractEventLoop) -> None:
        self.ws = websocket
        self.user_id = user_id
        self.project_id = project_id
        self.loop = loop
        self.session_id = uuid.uuid4().hex[:12]

        self.engine = "browser"
        self.language = "sw"
        self.ambient = False
        self.mode = "student"

        self.gate = AmbientGate()
        self.backchannel = BackchannelPolicy()
        self.engines = get_voice_engines()

        #: Set to cancel the running turn — this is what barge-in trips.
        self.cancel: threading.Event | None = None
        self.turn_active = False
        self.turn_id = ""

        #: Recent screen frames, newest last. See `_screen_context`.
        self.frames: list[dict] = []
        self.last_frame_at = 0.0

        self._audio_buf = bytearray()

    # -- sending (callable from the worker thread) -------------------------
    def send_threadsafe(self, payload: dict) -> None:
        """Queue a frame from the turn worker.

        The worker has no event loop, so everything goes back through the one
        captured when the socket opened.
        """
        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self._send(payload), self.loop)

    async def _send(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await self.ws.send_json(payload)

    # -- screen ------------------------------------------------------------
    def add_frame(self, data_b64: str) -> tuple[bool, str]:
        now = time.monotonic()
        if now - self.last_frame_at < MIN_FRAME_INTERVAL:
            return False, "too soon since the last frame"
        raw_len = (len(data_b64) * 3) // 4
        if raw_len > settings.screen_frame_max_bytes:
            return False, "frame too large; downscale before sending"
        self.last_frame_at = now
        self.frames.append({"data": data_b64, "at": time.time()})
        del self.frames[:-SCREEN_BUFFER]
        return True, ""

    def screen_note(self) -> str:
        """A text description of the shared screen for models without vision.

        Weave runs against whatever engine is configured, and the offline and
        smaller Ollama models cannot see an image at all. Rather than silently
        dropping the screen context, the turn carries an honest note saying a
        screen is being shared and how recently — so the assistant can ask the
        user to describe it instead of pretending to look.
        """
        if not self.frames:
            return ""
        age = max(0, int(time.time() - self.frames[-1]["at"]))
        return (
            "SCREEN SHARING IS ACTIVE. The user is sharing their screen and the "
            f"most recent frame arrived {age}s ago. If you cannot see images, say "
            "so plainly and ask them to describe or paste what is on screen — do "
            "not guess at its contents."
        )

    def vision_frames(self) -> list[str]:
        return [f["data"] for f in self.frames[-1:]]


def _user_from_token(token: str) -> str | None:
    if not token:
        return None
    payload = decode_ws_ticket(token)
    return payload.get("sub") if isinstance(payload, dict) else None


@router.websocket("/ws/session/{project_id}")
async def live_session(websocket: WebSocket, project_id: str, token: str = ""):
    user_id = _user_from_token(token)
    if not user_id:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            await websocket.close(code=4404)
            return
        mode = project.mode
        language = getattr(project.user, "preferred_language", "sw") if project.user else "sw"
    finally:
        db.close()

    await websocket.accept()
    session = LiveSession(websocket, user_id, project_id, asyncio.get_running_loop())
    session.mode = mode
    session.language = language or "sw"

    await websocket.send_json({
        "type": "ready",
        "session_id": session.session_id,
        "engines": session.engines.describe(),
        "language": session.language,
    })

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle(session, msg)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.debug("live session ended: %s", exc)
    finally:
        # A socket that drops while the assistant is talking must not leave a
        # worker generating into nothing.
        if session.cancel is not None:
            session.cancel.set()
        with contextlib.suppress(Exception):
            await websocket.close()


async def _handle(session: LiveSession, msg: dict) -> None:
    kind = str(msg.get("type") or "")

    if kind == "hello":
        session.engine = str(msg.get("engine") or "browser")
        session.language = str(msg.get("language") or session.language)
        session.ambient = bool(msg.get("ambient"))
        await session.ws.send_json({
            "type": "ready", "session_id": session.session_id,
            "engines": session.engines.describe(), "language": session.language,
            "ambient": session.ambient,
        })
        return

    if kind == "barge_in":
        # The whole point of duplex: the user talks over the assistant and it
        # stops immediately, mid-sentence, the way a person would.
        if session.turn_active and session.cancel is not None:
            session.cancel.set()
            await session.ws.send_json({"type": "interrupted"})
        return

    if kind == "frame":
        ok, reason = session.add_frame(str(msg.get("data") or ""))
        await session.ws.send_json({"type": "screen_noted", "accepted": ok, "reason": reason})
        return

    if kind == "screen_stop":
        session.frames.clear()
        await session.ws.send_json({"type": "screen_noted", "accepted": True, "reason": "stopped"})
        return

    if kind == "transcript":
        text = str(msg.get("text") or "")
        if not bool(msg.get("final")):
            # Interim result: this is where a listener would make a small noise
            # to show they are still there.
            cue = session.backchannel.maybe(text, session.language)
            if cue and not session.turn_active:
                await session.ws.send_json({"type": "backchannel", "text": cue})
            return
        await _maybe_respond(session, text)
        return

    if kind == "audio":
        if not session.engines.server_stt:
            await session.ws.send_json({
                "type": "error",
                "message": "this deployment has no server transcription; "
                           "use the browser engine",
            })
            return
        chunk = base64.b64decode(str(msg.get("data") or ""), validate=False)
        session._audio_buf.extend(chunk)
        if not bool(msg.get("final")):
            return
        audio = bytes(session._audio_buf)
        session._audio_buf.clear()
        result = await asyncio.to_thread(
            session.engines.transcribe, audio, session.language,
        )
        if not result.get("ok"):
            await session.ws.send_json({"type": "error", "message": result.get("error", "stt failed")})
            return
        await session.ws.send_json({"type": "heard", "text": result["text"], "responding": None})
        await _maybe_respond(session, result["text"])
        return

    if kind == "bye":
        if session.cancel is not None:
            session.cancel.set()
        await session.ws.close()
        return


async def _maybe_respond(session: LiveSession, text: str) -> None:
    """Apply the ambient gate, then run a turn if this was meant for us."""
    respond, why = session.gate.should_respond(text, ambient=session.ambient)
    await session.ws.send_json({
        "type": "heard", "text": text, "responding": respond, "why": why,
    })
    if not respond:
        return
    if session.turn_active:
        # Treat a new utterance during a turn as an interruption plus a new
        # request — which is what it is when someone talks over you.
        if session.cancel is not None:
            session.cancel.set()
        await session.ws.send_json({"type": "interrupted"})
        await asyncio.sleep(0.15)

    prompt = AmbientGate.strip_wake_word(text) if session.ambient else text
    await asyncio.to_thread(_run_turn, session, prompt)


def _run_turn(session: LiveSession, prompt: str) -> None:
    """Drive one orchestrator turn, speaking sentences as they are produced.

    Runs on a worker thread (see the module docstring). Everything it sends goes
    back through `send_threadsafe`.
    """
    from ..services.orchestration import get_orchestrator

    db: Session = SessionLocal()
    chunker = SentenceChunker()
    seq = 0
    spoken: list[str] = []
    session.turn_active = True
    session.cancel = threading.Event()

    def speak(chunk: str) -> None:
        nonlocal seq
        # Strip anything that is fine on screen and wrong in the ear. The chat
        # transcript keeps the original; only the spoken copy is cleaned.
        chunk = speakable(chunk)
        if not chunk:
            return
        seq += 1
        spoken.append(chunk)
        if session.engines.server_tts and session.engine == "server":
            out = session.engines.synthesise(chunk, session.language)
            if out.get("ok"):
                session.send_threadsafe({
                    "type": "audio", "seq": seq, "mime": out.get("mime", "audio/wav"),
                    "data": base64.b64encode(out["audio"]).decode("ascii"),
                    "text": chunk,
                })
                return
            # Synthesis failed — fall through to browser speech rather than
            # dropping the sentence entirely.
        session.send_threadsafe({"type": "say", "seq": seq, "text": chunk})

    try:
        project = db.query(Project).filter(Project.id == session.project_id).first()
        if project is None:
            session.send_threadsafe({"type": "error", "message": "project not found"})
            return

        # A shared screen becomes an explicit note in the user's turn. It is
        # honest about the model's limits rather than pretending to see.
        note = session.screen_note()
        text = f"{prompt}\n\n[{note}]" if note else prompt

        orch = get_orchestrator()
        session.send_threadsafe({"type": "turn_start", "turn_id": ""})

        for event in orch.stream_turn(
            db, project, text, session.language, thread_id=None, channel="voice",
            frames=session.vision_frames(),
        ):
            if session.cancel.is_set():
                break
            name, data = event.get("event"), event.get("data") or {}
            if name == "meta":
                session.turn_id = data.get("message_id") or ""
                session.send_threadsafe({"type": "turn_start", "turn_id": session.turn_id})
            elif name == "token":
                for chunk in chunker.push(data.get("text", "")):
                    if session.cancel.is_set():
                        break
                    speak(chunk)
            elif name == "step_start":
                # Spoken conversation cannot show a tool panel, so say what is
                # happening only when it will take long enough to be a silence.
                session.send_threadsafe({
                    "type": "step", "tool": data.get("tool", ""),
                    "title": data.get("title", ""),
                })
            elif name == "error":
                session.send_threadsafe({"type": "error", "message": data.get("message", "")})

        if not session.cancel.is_set():
            speak(chunker.flush())

        session.gate.note_spoke()
        session.send_threadsafe({
            "type": "turn_end",
            "turn_id": session.turn_id,
            "text": " ".join(spoken),
            "interrupted": session.cancel.is_set(),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("live turn failed: %s", exc)
        session.send_threadsafe({"type": "error", "message": str(exc)[:300]})
    finally:
        session.turn_active = False
        db.close()
