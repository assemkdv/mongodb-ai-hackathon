"""Measure Atlas Vector Search latency: embed the user's line + $vectorSearch.

Uses the timing the backend reports for each query (embedMs, searchMs,
totalMs), which excludes the network hop between this script and the backend.

Run (backend on :3001):
    uv run --project server python bench/bench_search.py
"""

import json
import statistics
from pathlib import Path

import httpx

from bench_turns import LINES, p95

API = "http://localhost:3001"
COUNTERPARTS = ["dana_reyes", "marcus_hale", "priya_shah"]


def main():
    timings = []
    with httpx.Client(timeout=30) as client:
        # 50 searches, cycling through the three counterparts and the 20 lines.
        for i in range(50):
            cid = COUNTERPARTS[i % 3]
            res = client.post(f"{API}/api/counterparts/{cid}/search", json={"text": LINES[i % 20]})
            res.raise_for_status()
            timings.append(res.json()["timing"])

    summary = {
        key: {
            "median": round(statistics.median(t[key] for t in timings)),
            "p95": p95([t[key] for t in timings]),
        }
        for key in ["embedMs", "searchMs", "totalMs"]
    }

    out = Path(__file__).parent / "results" / "vector_search.json"
    out.write_text(json.dumps({"summary": summary, "queries": timings}, indent=2) + "\n")
    for key, s in summary.items():
        print(f"{key:9} median {s['median']:4} ms   p95 {s['p95']:4} ms")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
