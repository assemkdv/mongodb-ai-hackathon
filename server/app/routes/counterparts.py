"""Counterparts: the people you rehearse against, and their traits.

Data model
----------
counterparts  one document per person (name, role, scenario, stance)
traits        one document per behaviour, e.g. "Becomes quiet when annoyed".
              Traits are never edited in place. A correction marks the old
              version "superseded" and inserts version + 1 as "active", so the
              full history of how the model of this person changed is kept.
evidence      why a trait exists or changed (e.g. the director's spoken note)
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agent import claude
from app.db import get_client, get_db, new_id
from app.embeddings import embed
from app.schemas import Correction, NewCounterpart, PersonaDescription

router = APIRouter(prefix="/api/counterparts")
log = logging.getLogger("uvicorn.error")


@router.get("")
async def list_counterparts():
    """All counterparts, each with how many active traits it has."""
    db = get_db()

    counterparts = (
        await db.counterparts.find({}, {"name": 1, "role": 1, "scenario": 1, "userRole": 1})
        .sort("name", 1)
        .to_list()
    )

    # Count active traits per counterpart in one database round trip.
    cursor = await db.traits.aggregate(
        [
            {"$match": {"status": "active"}},
            {"$group": {"_id": "$counterpartId", "activeTraits": {"$sum": 1}}},
        ]
    )
    counts = {row["_id"]: row["activeTraits"] for row in await cursor.to_list()}

    for c in counterparts:
        c["activeTraits"] = counts.get(c["_id"], 0)
    return {"counterparts": counterparts}


@router.post("", status_code=201)
async def create_counterpart(body: NewCounterpart):
    """Create a person and their version-1 traits in a single transaction."""
    db = get_db()

    # Readable id from the name ("Dana Reyes" -> "dana_reyes"), made unique if taken.
    base = body.id or re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")
    counterpart_id = base
    n = 2
    while await db.counterparts.find_one({"_id": counterpart_id}):
        counterpart_id = f"{base}_{n}"
        n += 1

    now = datetime.now(timezone.utc)
    counterpart = {
        "_id": counterpart_id,
        "name": body.name,
        "role": body.role,
        "userRole": body.userRole,
        "scenario": body.scenario,
        "wants": body.wants,
        "concessions": body.concessions,
        "boundaries": body.boundaries,
        "escalation": body.escalation,
        "speechRules": body.speechRules.model_dump(),
        "fictional": True,
        "createdAt": now,
        "updatedAt": now,
    }

    traits = []
    for category, value in body.traits.items():
        category = category.strip()
        if not category:
            raise HTTPException(400, "Trait categories must be non-empty")
        claim = value if isinstance(value, str) else value.claim
        confidence = 0.7 if isinstance(value, str) else value.confidence
        traits.append(
            {
                "_id": f"trait_{counterpart_id}_{category}_v1",
                "counterpartId": counterpart_id,
                "category": category,
                "claim": claim,
                "confidence": confidence,
                "status": "active",
                "version": 1,
                "evidenceIds": [],
                "createdAt": now,
                "updatedAt": now,
            }
        )

    # Both writes succeed together or neither does, so we never end up with a
    # person who has no traits.
    async def write(session):
        await db.counterparts.insert_one(counterpart, session=session)
        await db.traits.insert_many(traits, session=session)

    async with get_client().start_session() as session:
        await session.with_transaction(write)

    return {"counterpart": counterpart, "traits": traits}


@router.post("/generate", status_code=201)
async def generate_counterpart(body: PersonaDescription):
    """"My landlord Marcus, raising rent 22%..." -> a stored counterpart.

    Claude fills in the full profile (including one trait per category, so
    every behaviour can be corrected later), then it's saved like any other."""
    try:
        draft = await claude.draft_persona(body.description)
    except claude.Refused:
        raise HTTPException(422, "Could not build a persona from that description.")

    created = await create_counterpart(NewCounterpart.model_validate(draft))
    c = created["counterpart"]
    return {
        "counterpart": {
            "_id": c["_id"],
            "name": c["name"],
            "role": c["role"],
            "scenario": c["scenario"],
            "userRole": c["userRole"],
            "activeTraits": len(created["traits"]),
        }
    }


@router.get("/{counterpart_id}/context")
async def get_context(counterpart_id: str):
    """Everything needed to build the persona prompt: the person, their active
    traits, and the evidence behind those traits."""
    db = get_db()

    counterpart = await db.counterparts.find_one({"_id": counterpart_id})
    if not counterpart:
        raise HTTPException(404, "Counterpart not found")

    active_traits = (
        await db.traits.find({"counterpartId": counterpart_id, "status": "active"})
        .sort("category", 1)
        .to_list()
    )

    evidence_ids = [eid for trait in active_traits for eid in trait.get("evidenceIds", [])]
    # Leave out the 1024-number embeddings: the frontend never needs them.
    evidence = await db.evidence.find({"_id": {"$in": evidence_ids}}, {"embedding": 0}).to_list()

    return {"counterpart": counterpart, "activeTraits": active_traits, "evidence": evidence}


@router.post("/{counterpart_id}/corrections")
async def apply_correction(counterpart_id: str, body: Correction):
    """The "Director Interrupt": the user says the persona got someone wrong.

    Three writes, all in one transaction:
      1. insert the note as evidence
      2. mark the current trait in that category as superseded
      3. insert the corrected trait as the new active version
    If any step fails, none of them happen, so there is always exactly one
    active trait per category.
    """
    db = get_db()

    if not await db.counterparts.find_one({"_id": counterpart_id}):
        raise HTTPException(404, "Counterpart not found")

    previous = await db.traits.find_one(
        {"counterpartId": counterpart_id, "category": body.category, "status": "active"}
    )
    if not previous:
        raise HTTPException(
            404,
            f'No active trait found for counterpart "{counterpart_id}" '
            f'and category "{body.category}"',
        )

    now = datetime.now(timezone.utc)
    evidence_id = new_id("evidence")
    new_trait_id = new_id("trait")

    evidence = {
        "_id": evidence_id,
        "counterpartId": counterpart_id,
        "type": "user_correction",
        "content": body.correction,
        "source": "Director Interrupt",
        "reliability": 0.95,
        "referencesTraitId": previous["_id"],
        "createdAt": now,
    }
    new_trait = {
        "_id": new_trait_id,
        "counterpartId": counterpart_id,
        "category": body.category,
        "claim": body.correction,
        "confidence": 0.95,
        "status": "active",
        "version": previous.get("version", 1) + 1,
        "evidenceIds": [evidence_id],
        "supersedes": previous["_id"],
        "createdAt": now,
        "updatedAt": now,
    }
    superseded = {"status": "superseded", "supersededBy": new_trait_id, "updatedAt": now}

    # Embed the note so vector search can find it later. This is a network
    # call, so it happens *before* the transaction (keeping the transaction
    # short), and it's best-effort: if Voyage is down, the correction is still
    # saved, just not searchable until the backfill script runs.
    try:
        [evidence["embedding"]] = await embed([body.correction], "document")
    except Exception as error:
        log.warning("Could not embed correction %s: %s", evidence_id, error)

    async def write(session):
        await db.evidence.insert_one(evidence, session=session)
        await db.traits.update_one({"_id": previous["_id"]}, {"$set": superseded}, session=session)
        await db.traits.insert_one(new_trait, session=session)

    async with get_client().start_session() as session:
        await session.with_transaction(write)

    return {"supersededTrait": {**previous, **superseded}, "activeTrait": new_trait}
