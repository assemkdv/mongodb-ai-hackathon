def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "connected"}


def test_create_counterpart_makes_version_1_traits(client, counterpart):
    context = client.get(f"/api/counterparts/{counterpart['_id']}/context").json()
    traits = {t["category"]: t for t in context["activeTraits"]}

    assert traits["conflict_response"]["version"] == 1
    assert traits["conflict_response"]["confidence"] == 0.9
    assert traits["conversation_style"]["confidence"] == 0.7  # default for a plain string


def test_duplicate_names_get_unique_ids(client, counterpart):
    again = client.post(
        "/api/counterparts",
        json={"name": "Test Person", "role": "r", "scenario": "s", "traits": {"x": "y"}},
    )
    assert again.json()["counterpart"]["_id"] != counterpart["_id"]


def test_list_counts_active_traits(client, counterpart):
    listed = client.get("/api/counterparts").json()["counterparts"]
    mine = next(c for c in listed if c["_id"] == counterpart["_id"])
    assert mine["activeTraits"] == 2


def test_invalid_body_returns_400_with_error(client):
    res = client.post("/api/counterparts", json={"name": "  ", "role": "r", "scenario": "s"})
    assert res.status_code == 400
    assert "name" in res.json()["error"]


def test_unknown_counterpart_returns_404(client):
    res = client.get("/api/counterparts/nobody/context")
    assert res.status_code == 404
    assert res.json() == {"error": "Counterpart not found"}


def test_correction_supersedes_trait(client, counterpart):
    cid = counterpart["_id"]
    res = client.post(
        f"/api/counterparts/{cid}/corrections",
        json={"category": "conflict_response", "correction": "Gets loud when annoyed"},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["supersededTrait"]["status"] == "superseded"
    assert body["supersededTrait"]["supersededBy"] == body["activeTrait"]["_id"]
    assert body["activeTrait"]["version"] == 2
    assert body["activeTrait"]["supersedes"] == body["supersededTrait"]["_id"]

    # The context now shows the new claim, and the note is linked as evidence.
    context = client.get(f"/api/counterparts/{cid}/context").json()
    active = [t for t in context["activeTraits"] if t["category"] == "conflict_response"]
    assert len(active) == 1  # still exactly one active trait per category
    assert active[0]["claim"] == "Gets loud when annoyed"
    assert context["evidence"][0]["content"] == "Gets loud when annoyed"


def test_correction_for_unknown_category_returns_404(client, counterpart):
    res = client.post(
        f"/api/counterparts/{counterpart['_id']}/corrections",
        json={"category": "nope", "correction": "x"},
    )
    assert res.status_code == 404


def test_session_lifecycle(client, counterpart):
    session = client.post("/api/sessions", json={"counterpartId": counterpart["_id"]}).json()
    assert session["status"] == "active"
    sid = session["_id"]

    turn = client.post(
        f"/api/sessions/{sid}/turns",
        json={"speaker": "counterpart", "text": "No.", "delivery": {"pace": "slow"}},
    )
    assert turn.status_code == 201
    assert turn.json()["session"]["turns"][0]["text"] == "No."

    bad = client.post(f"/api/sessions/{sid}/turns", json={"speaker": "robot", "text": "hi"})
    assert bad.status_code == 400

    debrief = client.post(
        f"/api/sessions/{sid}/debrief",
        json=[
            {
                "timestamp": "2026-11-10T12:00:00Z",
                "title": "Held firm",
                "explanation": "Did not concede on price",
                "turnIds": [],
            }
        ],
    )
    assert debrief.status_code == 201

    # A completed session no longer accepts turns.
    closed = client.post(f"/api/sessions/{sid}/turns", json={"speaker": "user", "text": "hi"})
    assert closed.status_code == 400
    assert closed.json() == {"error": "Session is not active"}
