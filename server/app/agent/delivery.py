"""How the counterpart says a line, not just what it says.

Claude starts every reply with a delivery tag, e.g.
    [slow|flat|clipped] Eighty thousand. Not a dollar over.
pace | energy | manner. The tag is turned into ElevenLabs voice settings and
is stripped before synthesis, so it is never read aloud.
"""

import re

PACES = ("slow", "normal", "fast")
ENERGIES = ("flat", "warm", "sharp")
MANNERS = ("clipped", "measured", "dismissive")
DEFAULT = {"pace": "normal", "energy": "flat", "manner": "measured"}

# "[pace|energy|manner]" at the start, tolerant of spaces and capitals.
TAG = re.compile(r"^\s*\[\s*([a-z]+)\s*\|\s*([a-z]+)\s*\|\s*([a-z]+)\s*\]\s*", re.IGNORECASE)


def first_reply(raw: str) -> str:
    """Keep only the first tagged line.

    Claude occasionally writes two or three tagged lines in one reply
    ("[slow|flat|clipped] No.\n\n[fast|sharp|clipped] Not today."). The voice
    can only perform one, so everything from the second tag onward is dropped.
    """
    raw = raw.strip()
    second_tag = re.search(r"\n\s*\[[a-z]+\s*\|", raw, re.IGNORECASE)
    return raw[: second_tag.start()].strip() if second_tag else raw


def parse_delivery(raw: str) -> tuple[dict, str]:
    """Split a reply into (delivery, the words actually spoken)."""
    match = TAG.match(raw)
    if not match:
        return dict(DEFAULT), raw.strip()

    pace, energy, manner = (part.lower() for part in match.groups())
    delivery = {
        "pace": pace if pace in PACES else DEFAULT["pace"],
        "energy": energy if energy in ENERGIES else DEFAULT["energy"],
        "manner": manner if manner in MANNERS else DEFAULT["manner"],
    }
    return delivery, raw[match.end():].strip()


def voice_settings(delivery: dict) -> dict:
    """Map a delivery onto ElevenLabs voice settings.

    stability is counter-intuitive: high = monotone and consistent,
    low = emotionally variable. So "sharp" *lowers* stability.
    """
    settings = {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 1.0,
    }

    energy = {"flat": (0.88, 0.0), "warm": (0.45, 0.35), "sharp": (0.28, 0.55)}
    settings["stability"], settings["style"] = energy[delivery["energy"]]
    settings["speed"] = {"slow": 0.85, "normal": 1.0, "fast": 1.1}[delivery["pace"]]

    if delivery["manner"] == "clipped":  # tighter and a touch quicker, not emotive
        settings["speed"] += 0.05
        settings["stability"] += 0.1
    elif delivery["manner"] == "dismissive":
        settings["style"] += 0.15
        settings["speed"] += 0.03

    # Past ~0.9 stability the voice goes robotic; past ~0.6 style it slurs.
    settings["stability"] = clamp(settings["stability"], 0, 0.9)
    settings["style"] = clamp(settings["style"], 0, 0.6)
    settings["speed"] = clamp(settings["speed"], 0.7, 1.2)
    return settings


def shape_for_speech(line: str) -> str:
    """Turn "..." and "—" into pauses ElevenLabs actually honours."""
    line = re.sub(r"\s*—\s*", "— ", line)
    line = re.sub(r"\.{3,}", "... ", line)
    return re.sub(r"\s+", " ", line).strip()


def clamp(n: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, n))
