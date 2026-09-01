"""Shapes of the JSON bodies the API accepts.

Pydantic validates every request against these before our code runs, so the
route functions can assume the data is well-formed. A bad body gets a 400.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

# A string that is trimmed and must not be empty.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TraitInput(BaseModel):
    claim: Text
    confidence: float = 0.7


class SpeechRules(BaseModel):
    maximumWords: int = 35
    fragmentsWhenTense: bool = False
    usesFiller: bool = False


class NewCounterpart(BaseModel):
    # "_id" is optional: if missing, we build one from the name.
    id: str | None = Field(default=None, alias="_id")
    name: Text
    role: Text
    scenario: Text
    userRole: str | None = None
    wants: str = ""
    concessions: list[str] = []
    boundaries: list[str] = []
    escalation: str = ""
    speechRules: SpeechRules = SpeechRules()
    # Keyed by category, e.g. {"conflict_response": {"claim": "...", "confidence": 0.9}}.
    # A plain string is also accepted as the claim.
    traits: dict[str, Text | TraitInput] = Field(min_length=1)


class NewSession(BaseModel):
    counterpartId: Text


class NewTurn(BaseModel):
    speaker: Literal["user", "counterpart"]
    text: Text
    delivery: Any = None  # e.g. {"pace": "slow", "energy": "flat", "manner": "clipped"}


class Correction(BaseModel):
    category: Text
    correction: Text


class Observation(BaseModel):
    timestamp: datetime
    title: Text
    explanation: Text
    turnIds: list[Any]
    traitId: str | None = None


class DebriefBody(BaseModel):
    observations: list[Observation]
