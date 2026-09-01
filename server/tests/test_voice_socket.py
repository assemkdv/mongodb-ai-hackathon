"""The WebSocket voice loop (/ws/session)."""

import json


def receive_turn(ws):
    """Collect one turn's messages: audio bytes and JSON events."""
    audio, events = b"", []
    while True:
        message = ws.receive()
        if message.get("bytes"):
            audio += message["bytes"]
        elif message.get("text"):
            event = json.loads(message["text"])
            events.append(event)
            if event["type"] in ("done", "error"):
                return audio, events


def test_full_turn_streams_audio_then_reply_then_done(client, counterpart):
    """Real Claude + ElevenLabs call (costs well under a cent)."""
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({
            "type": "turn", "sessionId": "socket-test", "personaId": counterpart["_id"],
            "kind": "line", "text": "Can we talk about the rent increase?", "history": [],
        })
        audio, events = receive_turn(ws)

    types = [e["type"] for e in events]
    assert types == ["reply", "done"]
    assert events[0]["reply"].startswith("[")  # delivery tag included
    assert audio[:3] == b"ID3" or audio[:2] == b"\xff\xf3"  # MP3 data
    timing = events[1]["timing"]
    assert timing["firstAudioMs"] <= timing["totalMs"]


def test_bad_message_returns_an_error_event(client):
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "turn", "personaId": "dana-reyes"})  # missing fields
        _, events = receive_turn(ws)
    assert events[-1]["type"] == "error"


def test_unknown_persona_returns_an_error_event(client):
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({
            "type": "turn", "sessionId": "s", "personaId": "nobody",
            "kind": "line", "text": "hi", "history": [],
        })
        _, events = receive_turn(ws)
    assert events[-1] == {"type": "error", "error": "The persona could not respond: 404: Counterpart not found"}
