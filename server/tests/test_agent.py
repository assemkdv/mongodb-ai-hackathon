"""The agent's pure logic: no network, no database, runs instantly."""

from app.agent.delivery import first_reply, parse_delivery, shape_for_speech, voice_settings
from app.agent.prompt import build_system, to_messages


def test_parse_delivery_splits_tag_from_line():
    delivery, line = parse_delivery("[slow|flat|clipped] Eighty thousand.")
    assert delivery == {"pace": "slow", "energy": "flat", "manner": "clipped"}
    assert line == "Eighty thousand."


def test_unknown_or_missing_tag_falls_back_to_defaults():
    assert parse_delivery("No tag here.") == (
        {"pace": "normal", "energy": "flat", "manner": "measured"},
        "No tag here.",
    )
    delivery, _ = parse_delivery("[zoom|flat|clipped] Hi")
    assert delivery["pace"] == "normal"


def test_first_reply_keeps_only_the_first_tagged_line():
    raw = "[slow|flat|clipped] No.\n\n[fast|sharp|clipped] Not today."
    assert first_reply(raw) == "[slow|flat|clipped] No."


def test_first_reply_keeps_a_single_multiline_reply():
    assert first_reply("[slow|flat|clipped] No.\nNot today.") == "[slow|flat|clipped] No.\nNot today."


def test_sharp_voice_is_less_stable_than_flat():
    sharp = voice_settings({"pace": "normal", "energy": "sharp", "manner": "measured"})
    flat = voice_settings({"pace": "normal", "energy": "flat", "manner": "measured"})
    assert sharp["stability"] < flat["stability"]


def test_voice_settings_stay_in_safe_ranges():
    for energy in ["flat", "warm", "sharp"]:
        for manner in ["clipped", "measured", "dismissive"]:
            s = voice_settings({"pace": "fast", "energy": energy, "manner": manner})
            assert s["stability"] <= 0.9 and s["style"] <= 0.6 and 0.7 <= s["speed"] <= 1.2


def test_shape_for_speech_normalises_pauses():
    assert shape_for_speech("Well...  no—never") == "Well... no— never"


def test_prompt_includes_traits_and_vector_search_notes():
    context = {
        "counterpart": {
            "name": "Dana", "role": "VP Eng", "scenario": "Renewal.", "userRole": "Sam",
            "wants": "30% off", "concessions": ["12 months"], "boundaries": ["Never above $80k"],
            "escalation": "Goes silent", "speechRules": {"maximumWords": 30},
        },
        "activeTraits": [{"category": "conflict_response", "claim": "Goes quiet when annoyed"}],
    }
    system = build_system(context, [{"content": "Asks for a written incident report"}])
    assert "Goes quiet when annoyed" in system
    assert "RELEVANT PAST NOTES" in system and "written incident report" in system


def test_messages_always_start_with_the_user():
    history = [{"role": "persona", "text": "Hello."}, {"role": "user", "text": "Hi"}]
    messages = to_messages(history, "line", "Discount?")
    assert messages[0] == {"role": "user", "content": "Hi"}
    assert messages[-1] == {"role": "user", "content": "Discount?"}
