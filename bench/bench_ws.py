"""Measure voice latency over the WebSocket: time from sending the user's
line until the first byte of audio arrives back. Same 20 lines and same
definition as bench_turns.py (the HTTP baseline), so the numbers compare.

Run (backend on :3001):
    uv run --project server python bench/bench_ws.py <label>
"""

import asyncio
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

from websockets.asyncio.client import connect

from bench_turns import LINES, p95

URL = "ws://localhost:3001/ws/session"


async def main(label: str):
    session_id = f"bench-{uuid.uuid4()}"
    history, turns = [], []

    # One connection for the whole rehearsal, like the browser.
    async with connect(URL) as ws:
        for i, text in enumerate(LINES, start=1):
            sent = time.perf_counter()
            await ws.send(json.dumps({
                "type": "turn", "sessionId": session_id, "personaId": "dana-reyes",
                "kind": "line", "text": text, "history": history[-6:],
            }))

            first_audio = reply = server = None
            async for message in ws:
                if isinstance(message, bytes):
                    first_audio = first_audio or time.perf_counter()
                    continue
                data = json.loads(message)
                if data["type"] == "reply":
                    reply = data["reply"]
                elif data["type"] == "done":
                    server = data["timing"]
                    break
                elif data["type"] == "error":
                    raise RuntimeError(data["error"])

            ms = round((first_audio - sent) * 1000)
            turns.append({"time_to_first_audio_ms": ms, "server_prepare_ms": server["prepareMs"]})
            history += [
                {"role": "user", "text": text},
                {"role": "persona", "text": reply},
            ]
            print(f"{i:2}  {ms:5} ms   {reply[:60]}")

    summary = {
        key: {"median": round(statistics.median(t[key] for t in turns)), "p95": p95([t[key] for t in turns])}
        for key in turns[0]
    }
    out = Path(__file__).parent / "results" / f"{label}.json"
    out.write_text(json.dumps({"label": label, "summary": summary, "turns": turns}, indent=2) + "\n")
    print()
    for key, s in summary.items():
        print(f"{key:24} median {s['median']:5} ms   p95 {s['p95']:5} ms")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "ws"))
