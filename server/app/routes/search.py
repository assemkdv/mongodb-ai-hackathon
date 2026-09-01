"""Atlas Vector Search: find the past notes most relevant to what was just said.

Example: the user says "We'll give you a discount for the outage." The search
returns notes like "Dana repeatedly referenced the March outage..." even though
the words don't match exactly, because their embeddings are close in meaning.
Those notes are added to the persona prompt, so the counterpart stays
consistent with everything the director has taught it.
"""

import logging
import time

from fastapi import APIRouter, HTTPException

from app.db import get_db
from app.embeddings import embed
from app.schemas import SearchQuery

router = APIRouter(prefix="/api/counterparts")
log = logging.getLogger("uvicorn.error")

INDEX_NAME = "evidence_vector_index"


@router.post("/{counterpart_id}/search")
async def search_notes(counterpart_id: str, body: SearchQuery):
    db = get_db()
    if not await db.counterparts.find_one({"_id": counterpart_id}, {"_id": 1}):
        raise HTTPException(404, "Counterpart not found")

    started = time.perf_counter()

    # 1. Turn the user's line into a vector.
    [query_vector] = await embed([body.text], "query")
    embedded = time.perf_counter()

    # 2. Ask Atlas for the closest notes, only among this counterpart's notes.
    #    numCandidates: how many neighbours Atlas considers before picking the
    #    best `limit`. More candidates = more accurate, slightly slower.
    cursor = await db.evidence.aggregate(
        [
            {
                "$vectorSearch": {
                    "index": INDEX_NAME,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": 50,
                    "limit": body.limit,
                    "filter": {"counterpartId": counterpart_id},
                }
            },
            {
                "$project": {
                    "content": 1,
                    "type": 1,
                    "source": 1,
                    "score": {"$meta": "vectorSearchScore"},  # 0..1, higher = closer
                }
            },
        ]
    )
    results = await cursor.to_list()
    finished = time.perf_counter()

    timing = {
        "embedMs": round((embedded - started) * 1000),
        "searchMs": round((finished - embedded) * 1000),
        "totalMs": round((finished - started) * 1000),
    }
    log.info("vector search %s: %s", counterpart_id, timing)
    return {"results": results, "timing": timing}
