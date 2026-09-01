"""Builds the persona prompt from what MongoDB currently believes.

The character sheet is rebuilt on every turn from the *active* traits, so a
director correction changes the counterpart's behaviour on the very next line.
"""

KNOWN_CATEGORIES = [
    "conflict_response",
    "conversation_style",
    "negotiation_tactic",
    "hardening_trigger",
    "softening_trigger",
]


def build_system(context: dict, notes: list[dict]) -> str:
    c = context["counterpart"]
    traits = context["activeTraits"]

    def claims(*categories):
        return "\n".join(f"- {t['claim']}" for t in traits if t["category"] in categories)

    behaviour = claims("conflict_response", "conversation_style", "negotiation_tactic")
    # Categories the seed didn't anticipate still reach the prompt.
    other = "\n".join(f"- {t['claim']}" for t in traits if t["category"] not in KNOWN_CATEGORIES)
    hardens = claims("hardening_trigger") or "- (none recorded)"
    softens = claims("softening_trigger") or "- (none recorded)"

    # Results of Atlas Vector Search: past notes relevant to what was just said.
    memory = ""
    if notes:
        memory = (
            "\nRELEVANT PAST NOTES (what you have been told about how you behave "
            "in moments like this)\n" + "\n".join(f"- {n['content']}" for n in notes) + "\n"
        )

    user_role = c.get("userRole")
    them = f"the person you are speaking with ({user_role})" if user_role else "the other person"
    rules = c["speechRules"]
    speech = f"Under {rules['maximumWords']} words."
    if rules.get("fragmentsWhenTense"):
        speech += " Fragments when tense."
    if not rules.get("usesFiller"):
        speech += " No filler."

    return f"""You are {c['name']}, {c['role']}.
{c['scenario']}
You are speaking with {user_role or 'the other person'}.
Never mention being an AI. Never break character.

BEHAVIOR
{behaviour}{chr(10) + other if other else ''}

STANCE
Wants: {c['wants']}
Will concede: {'; '.join(c['concessions'])}
Never concedes: {'; '.join(c['boundaries'])}
If pushed: {c['escalation']}

REACTIONS
Hardens: {hardens}
Softens: {softens}
{memory}
SPEECH
{speech}

DELIVERY
Start your reply with [pace|energy|manner], then the line.
  pace: slow | normal | fast
  energy: flat | warm | sharp
  manner: clipped | measured | dismissive
Use "..." to trail off, "—" to cut yourself off.

RULES
Do not resolve this. Do not soften because {them} argued well once.
Concede only from the list, only after three turns of pressure.
Never coach {them}. Never say "that's fair."
Do not include internal or system XML tags in your response.
Reply with exactly one delivery tag and one line. Nothing else."""


def to_messages(history: list[dict], kind: str, text: str) -> list[dict]:
    """The conversation so far, in the shape the Claude API expects."""
    messages = []
    for turn in history:
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "persona":
            messages.append({"role": "assistant", "content": turn["text"]})

    if kind == "note":
        messages.append({
            "role": "user",
            "content": "[The director has corrected you. Deliver your last line again, "
            "the way the correction says you would. Same intent, new delivery.]",
        })
    else:
        messages.append({"role": "user", "content": text})

    # The API requires the conversation to start with the user.
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    return messages
