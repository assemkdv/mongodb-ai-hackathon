"""Load the built-in counterparts from seed_data.json into MongoDB.

Run:  uv run python seed.py

Safe to rerun: it only deletes and recreates the people listed in the file.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

people = json.loads((Path(__file__).parent / "seed_data.json").read_text())
db = MongoClient(os.environ["MONGODB_URI"])[os.getenv("MONGODB_DB", "counterpart")]
now = datetime.now(timezone.utc)

ids = [p["_id"] for p in people]
db.counterparts.delete_many({"_id": {"$in": ids}})
db.traits.delete_many({"counterpartId": {"$in": ids}})
db.evidence.delete_many({"counterpartId": {"$in": ids}})

for person in people:
    pid = person["_id"]
    trait_spec = person.pop("traits")
    evidence_spec = person.pop("evidence")

    db.counterparts.insert_one({**person, "fictional": True, "createdAt": now, "updatedAt": now})

    # Evidence first, so each trait can point at the evidence behind it.
    evidence_by_category = {}
    evidence_docs = []
    for i, e in enumerate(evidence_spec, start=1):
        evidence_id = f"evidence_{pid}_{i}"
        evidence_by_category[e["category"]] = evidence_id
        evidence_docs.append(
            {
                "_id": evidence_id,
                "counterpartId": pid,
                "type": e["type"],
                "content": e["content"],
                "source": e["source"],
                "reliability": e["reliability"],
                "createdAt": now,
            }
        )
    db.evidence.insert_many(evidence_docs)

    trait_docs = [
        {
            "_id": f"trait_{pid}_{category}_v1",
            "counterpartId": pid,
            "category": category,
            "claim": t["claim"],
            "confidence": t["confidence"],
            "status": "active",
            "version": 1,
            "evidenceIds": [evidence_by_category[category]] if category in evidence_by_category else [],
            "createdAt": now,
            "updatedAt": now,
        }
        for category, t in trait_spec.items()
    ]
    db.traits.insert_many(trait_docs)

    print(f"  {person['name']:<14} {len(trait_docs)} traits, {len(evidence_docs)} evidence")

print(f"\nSeeded {len(people)} counterparts into {db.name!r}")
