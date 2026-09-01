"""Turn text into embeddings with Voyage AI (MongoDB's embedding models).

An embedding is a list of 1024 numbers that captures what a piece of text
*means*. Texts with similar meanings get similar numbers, which is what lets
Atlas Vector Search find "relevant" notes rather than notes with matching words.
"""

import os

import httpx

MODEL = os.getenv("VOYAGE_MODEL", "voyage-3.5-lite")  # fast, 1024 dimensions
DIMENSIONS = 1024

# One shared HTTP client: reusing the connection saves a TLS handshake
# (~100ms) on every call.
_http: httpx.AsyncClient | None = None


async def embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed a batch of texts.

    input_type is "document" for things we store (director notes) and "query"
    for things we search with (what the user just said). Voyage tunes the
    vectors slightly differently for each, which improves search quality.
    """
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=10)

    base_url = os.getenv("VOYAGE_BASE_URL", "https://ai.mongodb.com/v1")
    response = await _http.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
        json={"input": texts, "model": MODEL, "input_type": input_type},
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]
