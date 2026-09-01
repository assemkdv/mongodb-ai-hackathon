"""Rehearsal Room API.

Run locally:  uv run uvicorn app.main:app --reload --port 3001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app import db
from app.embeddings import embed
from app.routes import counterparts, search, sessions, tts, turn, voice_socket


async def warm_up_embeddings():
    """Open the connection to Voyage at startup, so the first real search
    doesn't pay ~200ms of connection setup. Best-effort."""
    try:
        await embed(["warm up"], "query")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()  # runs once when the server starts
    await warm_up_embeddings()
    yield
    await db.disconnect()  # runs once when it stops


app = FastAPI(title="Rehearsal Room API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(counterparts.router)
app.include_router(search.router)
app.include_router(sessions.router)
app.include_router(turn.router)
app.include_router(tts.router)
app.include_router(voice_socket.router)


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok", "database": "connected"}


# Every error leaves the API as {"error": "..."}: the frontend reads that field.


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Turn Pydantic's error list into one readable message, e.g.
    '"name": String should have at least 1 character'."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"] if part != "body")
    message = f'"{field}": {first["msg"]}' if field else first["msg"]
    return JSONResponse({"error": message}, status_code=400)
