"""The WebSocket the browser keeps open for a whole rehearsal.

Bidirectional: both sides can send at any moment.

  browser -> server   {"type": "turn", ...same fields as POST /api/turn}
                      {"type": "cancel"}   the user interrupted (barge-in)

  server -> browser   binary frames         MP3 audio, played as it arrives
                      {"type": "reply", "reply": "...", ...}   the line's text
                      {"type": "done", "timing": {...}}
                      {"type": "error", "error": "..."}

Why a WebSocket instead of HTTP: the connection is opened once per rehearsal
(no handshake per turn), audio can be pushed the moment it exists, and the
browser can cancel a turn mid-sentence on the same connection.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.agent import claude
from app.agent.delivery import first_reply
from app.agent.voice_stream import speak_streaming
from app.routes.turn import prepare, save_transcript
from app.schemas import TurnRequest

router = APIRouter()
log = logging.getLogger("uvicorn.error")


@router.websocket("/ws/session")
async def session_socket(ws: WebSocket):
    await ws.accept()
    current: asyncio.Task | None = None  # the turn being spoken right now

    def cancel_current():
        if current and not current.done():
            current.cancel()

    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "cancel":
                cancel_current()
            elif message.get("type") == "turn":
                cancel_current()  # a new turn always replaces the old one
                current = asyncio.create_task(run_turn(ws, message))
    except WebSocketDisconnect:
        cancel_current()


async def run_turn(ws: WebSocket, message: dict) -> None:
    started = time.perf_counter()
    first_audio_ms = None

    def ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    try:
        body = TurnRequest.model_validate(message)
        prepared = await prepare(body)
        prepared_ms = ms()

        async def send_audio(chunk: bytes):
            nonlocal first_audio_ms
            if first_audio_ms is None:
                first_audio_ms = ms()
            await ws.send_bytes(chunk)

        async def send_reply(text: str):
            await ws.send_json({"type": "reply", "reply": first_reply(text), **prepared.result})

        marks = {}
        reply = await speak_streaming(
            claude.stream_reply(prepared.system, prepared.messages), send_audio, send_reply, marks
        )

        # Where the time went, each stage measured from the moment the line arrived.
        timing = {
            "prepareMs": prepared_ms,  # database + vector search
            **{f"{name}Ms": round((t - started) * 1000) for name, t in marks.items()},
            "firstAudioMs": first_audio_ms,
            "totalMs": ms(),
        }
        log.info("voice turn %s: %s", body.personaId, timing)
        await ws.send_json({"type": "done", "timing": timing})

        # Save the transcript after the user has heard the reply.
        asyncio.create_task(save_transcript(prepared.session_id, body, first_reply(reply)))

    except asyncio.CancelledError:
        raise  # barge-in: stop quietly
    except ValidationError as error:
        await ws.send_json({"type": "error", "error": f"Bad turn message: {error.errors()[0]['msg']}"})
    except claude.Refused:
        await ws.send_json({"type": "error", "error": "The persona declined to respond to that."})
    except Exception as error:
        log.exception("voice turn failed")
        await ws.send_json({"type": "error", "error": f"The persona could not respond: {error}"})
