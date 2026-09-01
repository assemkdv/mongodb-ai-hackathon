"""Measure voice latency: how long from "the user finished speaking" until the
first byte of the counterpart's audio arrives.

This version measures the current HTTP flow:
    POST /api/chat  (wait for Claude's full reply)
    POST /api/tts   (wait for the first audio byte)

Run (with the backend on :3001 and the frontend on :3000):
    uv run --project server python bench/bench_turns.py before
"""

import json
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx

APP = "http://localhost:3000"

# Twenty things a vendor might say to Dana in a contract negotiation.
LINES = [
    "Hi Dana, thanks for making time. I wanted to talk about the renewal.",
    "We can offer five percent off if you renew for two years.",
    "I understand the March outage hurt. We've fixed the root cause.",
    "What would it take to get this signed this quarter?",
    "Our pricing is in line with the market for this tier.",
    "Your team uses the product every day. Switching would be expensive.",
    "Could we talk about a twelve month term instead?",
    "I can go to ten percent, but that's the most I can do today.",
    "What does Priya need to see to approve this?",
    "We added three features your engineers asked for last year.",
    "Honestly, we dropped the ball in March. I'm not going to pretend otherwise.",
    "If you walk away, migration alone will take your team months.",
    "What's your budget ceiling for this contract?",
    "I can include premium support at no extra cost.",
    "Let me be specific: ninety two thousand for twelve months.",
    "Is the price the only thing standing in the way?",
    "We'd credit you two months for the outage.",
    "Can we get a call with Priya next week?",
    "Eighty five thousand, twelve months, premium support included.",
    "Okay. What would make this a yes for you today?",
]


def p95(values):
    return sorted(values)[int(round(0.95 * (len(values) - 1)))]


def run_turn(client, session_id, history, text):
    start = time.perf_counter()

    chat = client.post(
        f"{APP}/api/chat",
        json={
            "sessionId": session_id,
            "personaId": "dana-reyes",
            "kind": "line",
            "text": text,
            "history": history[-6:],
        },
    )
    chat.raise_for_status()
    reply = chat.json()["reply"]
    reply_done = time.perf_counter()

    with client.stream("POST", f"{APP}/api/tts", json={"text": reply}) as audio:
        audio.raise_for_status()
        stream = audio.iter_bytes()
        next(stream)  # first audio byte
        first_audio = time.perf_counter()
        for _ in stream:  # drain the rest so the connection is clean
            pass

    return reply, {
        "claude_ms": round((reply_done - start) * 1000),
        "tts_first_byte_ms": round((first_audio - reply_done) * 1000),
        "time_to_first_audio_ms": round((first_audio - start) * 1000),
    }


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    session_id = f"bench-{uuid.uuid4()}"
    history, turns = [], []

    with httpx.Client(timeout=60) as client:
        for i, text in enumerate(LINES, start=1):
            reply, timing = run_turn(client, session_id, history, text)
            turns.append(timing)
            history += [
                {"id": f"u{i}", "role": "user", "text": text, "at": 0},
                {"id": f"p{i}", "role": "persona", "text": reply, "at": 0},
            ]
            print(f"{i:2}  {timing['time_to_first_audio_ms']:5} ms   {reply[:60]}")

    summary = {}
    for key in turns[0]:
        values = [t[key] for t in turns]
        summary[key] = {"median": round(statistics.median(values)), "p95": p95(values)}

    out = Path(__file__).parent / "results" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"label": label, "summary": summary, "turns": turns}, indent=2) + "\n")

    print()
    for key, s in summary.items():
        print(f"{key:24} median {s['median']:5} ms   p95 {s['p95']:5} ms")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
