"""One shared HTTP client for outside APIs (Voyage, ElevenLabs).

Reusing one client keeps connections open between calls, which saves a TLS
handshake (~100ms) on every request after the first.
"""

import httpx

_http: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=30)
    return _http
