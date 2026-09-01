"""Sessions: one rehearsal, its transcript, and the debrief at the end.

sessions   one document per rehearsal; turns are appended to its "turns" array
debriefs   observations written after the session ends
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pymongo import ReturnDocument

from app.db import get_db, new_id
from app.schemas import DebriefBody, NewSession, NewTurn, Observation

router = APIRouter(prefix="/api/sessions")


@router.post("", status_code=201)
async def create_session(body: NewSession):
    db = get_db()

    if not await db.counterparts.find_one({"_id": body.counterpartId}):
        raise HTTPException(404, "Counterpart not found")

    now = datetime.now(timezone.utc)
    session = {
        "_id": new_id("session"),
        "counterpartId": body.counterpartId,
        "status": "active",
        "turns": [],
        "startedAt": now,
        "updatedAt": now,
    }
    await db.sessions.insert_one(session)
    return session


@router.post("/{session_id}/turns", status_code=201)
async def add_turn(session_id: str, body: NewTurn):
    """Append one line of dialogue to the transcript."""
    db = get_db()

    session = await db.sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "active":
        raise HTTPException(400, "Session is not active")

    now = datetime.now(timezone.utc)
    turn = {
        "_id": new_id("turn"),
        "speaker": body.speaker,
        "text": body.text,
        "delivery": body.delivery,
        "timestamp": now,
    }

    # $push appends in place: no need to read, modify and rewrite the whole array.
    updated = await db.sessions.find_one_and_update(
        {"_id": session_id},
        {"$push": {"turns": turn}, "$set": {"updatedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
    return {"turn": turn, "session": updated}


@router.post("/{session_id}/debrief", status_code=201)
async def create_debrief(session_id: str, body: DebriefBody | list[Observation]):
    """Save the debrief and close the session. Accepts either
    {"observations": [...]} or a bare list of observations."""
    db = get_db()
    observations = body.observations if isinstance(body, DebriefBody) else body

    session = await db.sessions.find_one({"_id": session_id})
    if not session:
        raise HTTPException(404, "Session not found")

    now = datetime.now(timezone.utc)
    debrief = {
        "_id": new_id("debrief"),
        "sessionId": session_id,
        "counterpartId": session["counterpartId"],
        "observations": [o.model_dump() for o in observations],
        "createdAt": now,
    }
    await db.debriefs.insert_one(debrief)
    await db.sessions.update_one(
        {"_id": session_id},
        {"$set": {"status": "completed", "completedAt": now, "updatedAt": now}},
    )
    return debrief
