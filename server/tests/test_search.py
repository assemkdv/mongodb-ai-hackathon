import time


def correct(client, cid, category, text):
    res = client.post(
        f"/api/counterparts/{cid}/corrections", json={"category": category, "correction": text}
    )
    assert res.status_code == 200


def search(client, cid, text):
    """Atlas indexes new vectors within about a second, so retry briefly."""
    for _ in range(20):
        res = client.post(f"/api/counterparts/{cid}/search", json={"text": text})
        assert res.status_code == 200
        if len(res.json()["results"]) >= 2:
            return res.json()
        time.sleep(0.5)
    raise AssertionError("notes never became searchable")


def test_search_returns_the_most_relevant_note(client, counterpart):
    cid = counterpart["_id"]
    correct(client, cid, "conflict_response", "Raises his voice and talks over people when challenged")
    correct(client, cid, "conversation_style", "Always brings up the leaking boiler when money is mentioned")

    body = search(client, cid, "Why are you shouting at me?")

    assert "voice" in body["results"][0]["content"]
    assert set(body["timing"]) == {"embedMs", "searchMs", "totalMs"}


def test_search_only_returns_this_counterparts_notes(client, counterpart):
    other = client.post(
        "/api/counterparts",
        json={"name": "Someone Else", "role": "r", "scenario": "s", "traits": {"style": "x"}},
    ).json()["counterpart"]
    correct(client, other["_id"], "style", "Hums loudly during every meeting")

    results = client.post(
        f"/api/counterparts/{counterpart['_id']}/search", json={"text": "humming in meetings"}
    ).json()["results"]

    assert all("Hums" not in r["content"] for r in results)


def test_embeddings_are_not_sent_to_the_frontend(client, counterpart):
    cid = counterpart["_id"]
    correct(client, cid, "conflict_response", "Gets loud")
    evidence = client.get(f"/api/counterparts/{cid}/context").json()["evidence"]
    assert evidence and all("embedding" not in e for e in evidence)


def test_search_unknown_counterpart_returns_404(client):
    res = client.post("/api/counterparts/nobody/search", json={"text": "hi"})
    assert res.status_code == 404
