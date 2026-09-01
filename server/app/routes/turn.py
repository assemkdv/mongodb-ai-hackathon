"""One rehearsal turn: the heart of the voice agent.

    browser ──▶ POST /api/turn
                 ├─ MongoDB              who this person is (active traits)
                 ├─ Atlas Vector Search  past notes relevant to what was said
                 ├─ Claude               classify a director note, or reply in character
                 └─ MongoDB              save the transcript (after responding)

kind = "line": the user said something in the scene; the counterpart replies.
kind = "note": the director corrected the counterpart ("she'd get louder, not
quieter"). The note becomes new trait versions, then the counterpart redoes
its last line the corrected way.
"""

import asyncio
import logging
from datetime import datetime, timezone

import anthropic
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent import claude
from app.agent.delivery import first_reply, parse_delivery
from app.agent.prompt import build_system, to_messages
from app.db import get_db, new_id
from app.routes.counterparts import apply_correction, get_context
from app.routes.search import search_notes
from app.routes.sessions import add_turn
from app.schemas import Correction, NewTurn, SearchQuery, TurnRequest

router = APIRouter()
log = logging.getLogger("uvicorn.error")


@router.post("/api/turn")
async def turn(body: TurnRequest, background: BackgroundTasks):
    counterpart_id = body.personaId.replace("-", "_")  # "dana-reyes" -> "dana_reyes"

    # Start the vector search now and let it run while we load everything else.
    notes = (
        asyncio.create_task(relevant_notes(counterpart_id, body.text))
        if body.kind == "line"
        else None
    )

    context = await get_context(counterpart_id)
    session_id = await ensure_session(body.sessionId, counterpart_id)

    result = {}
    if body.kind == "note":
        try:
            result = await apply_note(counterpart_id, context, body.text)
            # Re-read so the retake is generated against the corrected persona.
            context = await get_context(counterpart_id)
        except Exception as error:
            log.warning("correction failed: %s", error)
            result = {"degraded": f"Could not store that correction: {error}"}

    system = build_system(context, await notes if notes else [])

    try:
        raw = await claude.reply(system, to_messages([h.model_dump() for h in body.history], body.kind, body.text))
    except claude.Refused:
        raise HTTPException(422, "The persona declined to respond to that.")
    except anthropic.APIError as error:
        log.error("Claude error: %s", error)
        raise HTTPException(502, "The persona could not respond.")

    reply = first_reply(raw)
    if not reply:
        raise HTTPException(502, "Empty reply from the model")

    # Saving the transcript must never delay the reply the user is waiting for.
    background.add_task(save_transcript, session_id, body, reply)
    return {"reply": reply, **result}


async def relevant_notes(counterpart_id: str, text: str) -> list[dict]:
    """Vector search, best-effort: if it fails, the turn goes on without it."""
    try:
        return (await search_notes(counterpart_id, SearchQuery(text=text)))["results"]
    except Exception as error:
        log.warning("vector search failed: %s", error)
        return []


async def apply_note(counterpart_id: str, context: dict, note: str) -> dict:
    """A spoken note can touch more than one trait ("he'd go cold, not stay
    chatty" changes both conflict_response and conversation_style), so Claude
    maps it to categories first, then each one is superseded in a transaction."""
    revisions = await claude.classify_note(context["activeTraits"], note)

    applied = []
    for r in revisions:
        correction = Correction(category=r["category"], correction=r["claim"])
        applied.append((await apply_correction(counterpart_id, correction))["activeTrait"])

    more = f" +{len(applied) - 1} more" if len(applied) > 1 else ""
    return {
        "correction": {"id": applied[0]["_id"], "summary": " ".join(r["claim"] for r in revisions)},
        "memoryWrite": {"collection": "traits", "documentId": applied[0]["_id"] + more},
    }


async def ensure_session(client_id: str, counterpart_id: str) -> str:
    """Map the browser's session id to a session document, creating it once."""
    db = get_db()
    existing = await db.sessions.find_one({"clientId": client_id, "status": "active"}, {"_id": 1})
    if existing:
        return existing["_id"]

    now = datetime.now(timezone.utc)
    session = {
        "_id": new_id("session"),
        "clientId": client_id,
        "counterpartId": counterpart_id,
        "status": "active",
        "turns": [],
        "startedAt": now,
        "updatedAt": now,
    }
    await db.sessions.insert_one(session)
    return session["_id"]


async def save_transcript(session_id: str, body: TurnRequest, reply: str) -> None:
    delivery, line = parse_delivery(reply)
    try:
        # A director note isn't dialogue: it became a trait, not a turn.
        if body.kind == "line":
            await add_turn(session_id, NewTurn(speaker="user", text=body.text))
        await add_turn(session_id, NewTurn(speaker="counterpart", text=line, delivery=delivery))
    except Exception as error:
        log.warning("transcript logging failed: %s", error)
