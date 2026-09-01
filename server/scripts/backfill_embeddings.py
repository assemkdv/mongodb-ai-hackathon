"""Add embeddings to evidence saved before vector search existed (e.g. seed data).

Run:  uv run python -m scripts.backfill_embeddings

Safe to rerun: it only touches documents that don't have an embedding yet.
"""

import asyncio
import os

from dotenv import load_dotenv
from pymongo import MongoClient

from app.embeddings import embed


def backfill(db) -> int:
    missing = list(db.evidence.find({"embedding": {"$exists": False}}, {"content": 1}))
    if not missing:
        return 0

    # One API call for the whole batch instead of one per document.
    vectors = asyncio.run(embed([doc["content"] for doc in missing], "document"))
    for doc, vector in zip(missing, vectors):
        db.evidence.update_one({"_id": doc["_id"]}, {"$set": {"embedding": vector}})
    return len(missing)


if __name__ == "__main__":
    load_dotenv()
    client = MongoClient(os.environ["MONGODB_URI"])
    count = backfill(client[os.getenv("MONGODB_DB", "counterpart")])
    print(f"Embedded {count} evidence documents")
