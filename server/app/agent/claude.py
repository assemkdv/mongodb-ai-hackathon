"""Every call to Claude lives here.

Three jobs:
  reply()           the counterpart's next in-character line
  classify_note()   map a spoken director note onto the trait(s) it corrects
  draft_persona()   turn a free-text description into a full counterpart
"""

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()  # the API key and model settings live in server/.env

MODEL = os.getenv("CHAT_MODEL", "claude-opus-5")
EFFORT = os.getenv("CHAT_EFFORT", "low")

# Reads ANTHROPIC_API_KEY from the environment. One client, reused.
client = anthropic.AsyncAnthropic()


class Refused(Exception):
    """Claude declined to answer (stop_reason == "refusal")."""


def _text(message) -> str:
    if message.stop_reason == "refusal":
        raise Refused()
    return "".join(b.text for b in message.content if b.type == "text").strip()


def _fast_settings() -> dict:
    """Keep replies quick: a rehearsal partner that pauses to deliberate stops
    feeling like a person, and short in-character lines don't need extended
    reasoning. Each model family switches thinking off a little differently."""
    if MODEL.startswith("claude-sonnet-5-5"):
        thinking = {"type": "between_tools"}
    elif MODEL.startswith(("claude-opus-5-5", "claude-fable")):
        return {"output_config": {"effort": EFFORT}}  # thinking can't be disabled; low effort instead
    else:
        thinking = {"type": "disabled"}
    return {"thinking": thinking, "output_config": {"effort": EFFORT}}


async def reply(system: str, messages: list[dict]) -> str:
    """The whole reply at once (used by the HTTP endpoint)."""
    message = await client.messages.create(
        model=MODEL, max_tokens=1024, system=system, messages=messages, **_fast_settings()
    )
    return _text(message)


async def stream_reply(system: str, messages: list[dict]):
    """The reply token by token, as Claude writes it (used by the WebSocket).
    Lets the voice start speaking before the sentence is finished."""
    async with client.messages.stream(
        model=MODEL, max_tokens=1024, system=system, messages=messages, **_fast_settings()
    ) as stream:
        async for text in stream.text_stream:
            yield text
        if (await stream.get_final_message()).stop_reason == "refusal":
            raise Refused()


async def classify_note(active_traits: list[dict], note: str) -> list[dict]:
    """"She'd get louder, not quieter" -> [{"category": "conflict_response",
    "claim": "Raises her voice when annoyed"}].

    The schema restricts `category` to categories this person actually has,
    so Claude can't invent one the database would reject.
    """
    categories = [t["category"] for t in active_traits]
    current = "\n".join(f"- {t['category']}: {t['claim']}" for t in active_traits)

    message = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking=_fast_settings().get("thinking", anthropic.omit),
        output_config={
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "revisions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {"type": "string", "enum": categories},
                                    "claim": {
                                        "type": "string",
                                        "description": "The corrected trait, rewritten as a "
                                        "third-person statement about how they behave. "
                                        "Under 15 words.",
                                    },
                                },
                                "required": ["category", "claim"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["revisions"],
                    "additionalProperties": False,
                },
            },
        },
        system="You maintain a behavioural model of a person. The director just "
        "corrected it. Revise every existing trait the correction contradicts — "
        "usually one, but if another trait would still produce the behaviour the "
        "director just rejected, revise that one too. Do not revise traits the "
        "correction leaves untouched. One revision per category.",
        messages=[{
            "role": "user",
            "content": f'Current traits:\n{current}\n\nDirector\'s correction: "{note}"',
        }],
    )

    revisions, seen = [], set()
    for r in json.loads(_text(message))["revisions"]:
        # One revision per category: two would fight over the same trait.
        if r["category"] in categories and r["category"] not in seen:
            seen.add(r["category"])
            revisions.append(r)
    if not revisions:
        raise ValueError("classifier matched no known trait category")
    return revisions[:3]  # one note shouldn't rewrite the whole personality


PERSONA_CATEGORIES = [
    "conflict_response",
    "conversation_style",
    "negotiation_tactic",
    "hardening_trigger",
    "softening_trigger",
]

PERSONA_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Their full name."},
        "role": {"type": "string", "description": "Their role, e.g. 'Landlord of your building'."},
        "userRole": {
            "type": "string",
            "description": "Who the rehearsing user is in this scene, e.g. 'his tenant of four years'.",
        },
        "scenario": {
            "type": "string",
            "description": "One sentence, third person, naming the situation and what is at stake.",
        },
        "wants": {"type": "string", "description": "What they want out of this conversation."},
        "concessions": {"type": "array", "items": {"type": "string"},
                        "description": "What they will give up, under pressure."},
        "boundaries": {"type": "array", "items": {"type": "string"},
                       "description": "What they will never agree to."},
        "escalation": {"type": "string", "description": "What they do if pushed too far."},
        "speechRules": {
            "type": "object",
            "properties": {
                "maximumWords": {"type": "integer"},
                "fragmentsWhenTense": {"type": "boolean"},
                "usesFiller": {"type": "boolean"},
            },
            "required": ["maximumWords", "fragmentsWhenTense", "usesFiller"],
            "additionalProperties": False,
        },
        "traits": {
            "type": "object",
            "properties": {
                category: {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string",
                                  "description": "Third-person statement about how they behave. Under 15 words."},
                        "confidence": {"type": "number"},
                    },
                    "required": ["claim", "confidence"],
                    "additionalProperties": False,
                }
                for category in PERSONA_CATEGORIES
            },
            "required": PERSONA_CATEGORIES,
            "additionalProperties": False,
        },
    },
    "required": ["name", "role", "userRole", "scenario", "wants", "concessions",
                 "boundaries", "escalation", "speechRules", "traits"],
    "additionalProperties": False,
}


async def draft_persona(description: str) -> dict:
    """Free-text description -> the body POST /api/counterparts expects,
    with one trait per correctable category."""
    message = await client.messages.create(
        model=MODEL,
        max_tokens=2048,
        thinking=_fast_settings().get("thinking", anthropic.omit),
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": PERSONA_SCHEMA}},
        system="You build behavioural models of people for rehearsal practice. Given "
        "a description of someone and a situation, produce a model of how they "
        "behave in it. Stay concrete and specific to this person — no generic "
        "traits that would fit anyone. Where the description is silent, infer "
        "something plausible for this role and situation rather than hedging. "
        "These are practice personas, not real people; give them firm positions "
        "so there is something to push against.",
        messages=[{"role": "user", "content": description}],
    )
    return json.loads(_text(message))
