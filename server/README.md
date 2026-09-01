# Rehearsal Room API (FastAPI + MongoDB)

## Run it

```bash
cd server
cp .env.example .env          # then fill in the Atlas, Voyage, Anthropic and ElevenLabs keys
uv run python seed.py                         # 3 built-in counterparts
uv run python -m scripts.backfill_embeddings  # embed their notes
uv run python -m scripts.create_vector_index  # Atlas Vector Search index (once)
uv run uvicorn app.main:app --reload --port 3001
```

Interactive API docs: http://localhost:3001/docs

The frontend already talks to `http://localhost:3001` (`BACKEND_URL` in `frontend/.env.local`).

## Test it

```bash
uv run pytest -q
```

The tests use a separate `counterpart_test` database and drop it afterwards.
No Atlas yet? Run MongoDB locally in Docker:

```bash
docker run -d --name rehearsal-mongo -p 27018:27017 mongodb/mongodb-atlas-local:8.0
MONGODB_URI="mongodb://localhost:27018/?directConnection=true" uv run pytest -q
```

## Files

| File | What it does |
|---|---|
| `app/main.py` | Creates the app, connects to MongoDB on startup, formats errors as `{"error": ...}` |
| `app/db.py` | The single shared MongoDB client, plus indexes |
| `app/schemas.py` | Pydantic models: the allowed shape of every request body |
| `app/routes/counterparts.py` | People, their versioned traits, and the correction transaction |
| `app/routes/sessions.py` | Rehearsal sessions, transcript turns, debriefs |
| `app/routes/search.py` | Atlas Vector Search: top 3 past notes relevant to a line, with timing |
| `app/embeddings.py` | Voyage AI: text in, 1024-number embedding out |
| `app/routes/turn.py` | **The voice agent:** one rehearsal turn (context + vector search + Claude + transcript) |
| `app/routes/tts.py` | Streams a line of speech from ElevenLabs with voice settings from the delivery tag |
| `app/agent/claude.py` | Every Claude call: in-character reply, director-note classifier, persona drafting |
| `app/agent/prompt.py` | Builds the persona prompt from active traits + vector search notes |
| `app/agent/delivery.py` | `[pace\|energy\|manner]` tag → ElevenLabs voice settings |
| `app/http.py` | One shared HTTP client for Voyage and ElevenLabs |
| `scripts/create_vector_index.py` | Creates the `evidence_vector_index` in Atlas |
| `scripts/backfill_embeddings.py` | Embeds notes saved before vector search existed |
| `tests/test_api.py` | One test per behaviour, run against a real MongoDB |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Server and database are up |
| GET | `/api/counterparts` | List people, with active-trait counts |
| POST | `/api/counterparts` | Create a person + version-1 traits (transaction) |
| GET | `/api/counterparts/{id}/context` | Person + active traits + evidence, for building the prompt |
| POST | `/api/counterparts/{id}/corrections` | Director note: embed it, then supersede a trait (3-write transaction) |
| POST | `/api/counterparts/{id}/search` | Vector search: the 3 past notes closest in meaning to `text` |
| POST | `/api/sessions` | Start a rehearsal |
| POST | `/api/sessions/{id}/turns` | Append a line to the transcript |
| POST | `/api/sessions/{id}/debrief` | Save the debrief and close the session |
| POST | `/api/turn` | One rehearsal turn: line or director note → in-character reply |
| POST | `/api/tts` | Stream the reply as audio (MPEG) |
| POST | `/api/counterparts/generate` | Free-text description → stored counterpart (Claude) |
