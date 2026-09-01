"""Create the Atlas Vector Search index on evidence.embedding.

Run once per database:  uv run python -m scripts.create_vector_index

The index tells Atlas: "the `embedding` field holds 1024-number vectors;
compare them with cosine similarity; and let queries filter by counterpartId"
(so a search for Dana only ever returns Dana's notes).
"""

import os
import time

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from app.embeddings import DIMENSIONS

INDEX_NAME = "evidence_vector_index"


def ensure_vector_index(db) -> None:
    # Atlas can only index a collection that exists.
    if "evidence" not in db.list_collection_names():
        db.create_collection("evidence")

    existing =[ix["name"] for ix in db.evidence.list_search_indexes()]
    if INDEX_NAME not in existing:
        db.evidence.create_search_index(
            SearchIndexModel(
                name=INDEX_NAME,
                type="vectorSearch",
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "path": "embedding",
                            "numDimensions": DIMENSIONS,
                            "similarity": "cosine",
                        },
                        {"type": "filter", "path": "counterpartId"},
                    ]
                },
            )
        )
        print(f"Creating {INDEX_NAME}...")

    # Atlas builds the index in the background; wait until it can be queried.
    while True:
        index = next(ix for ix in db.evidence.list_search_indexes() if ix["name"] == INDEX_NAME)
        if index.get("queryable"):
            print(f"{INDEX_NAME} is ready on {db.name}.evidence")
            return
        time.sleep(3)


if __name__ == "__main__":
    load_dotenv()
    client = MongoClient(os.environ["MONGODB_URI"])
    ensure_vector_index(client[os.getenv("MONGODB_DB", "counterpart")])
