"""MongoDB connection.

One client is opened when the server starts and shared by every request.
Opening a new connection per request would add ~100ms+ to each call.
"""

import os
import uuid

from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

load_dotenv()

_client: AsyncMongoClient | None = None


async def connect() -> None:
    """Open the connection and make sure the indexes our queries rely on exist."""
    global _client
    # tz_aware: dates come back as UTC, not as "naive" times with no timezone.
    _client = AsyncMongoClient(os.environ["MONGODB_URI"], tz_aware=True)
    db = get_db()
    await db.command("ping")

    # Each index matches a query the routes actually run.
    await db.traits.create_index([("counterpartId", 1), ("category", 1), ("status", 1)])
    await db.sessions.create_index([("counterpartId", 1), ("startedAt", -1)])
    await db.evidence.create_index([("counterpartId", 1), ("createdAt", -1)])
    await db.debriefs.create_index("sessionId")


async def disconnect() -> None:
    if _client is not None:
        await _client.close()


def get_client() -> AsyncMongoClient:
    """The client is needed (not just the db) to start a transaction."""
    if _client is None:
        raise RuntimeError("Database not connected. Was the app started?")
    return _client


def get_db() -> AsyncDatabase:
    return get_client()[os.getenv("MONGODB_DB", "counterpart")]


def new_id(prefix: str) -> str:
    """Readable, unique ids like "session_3f2b...". Easier to debug than ObjectIds."""
    return f"{prefix}_{uuid.uuid4()}"
