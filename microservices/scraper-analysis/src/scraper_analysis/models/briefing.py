from typing import Literal

from pydantic import BaseModel, Field, field_validator

Theme = Literal["news", "insider", "congressional", "filing", "social", "market", "commodity", "other"]
Direction = Literal["positive", "negative", "mixed", "neutral"]

_THEMES = set(Theme.__args__)
_DIRECTIONS = set(Direction.__args__)


class BriefingPoint(BaseModel):
    theme: Theme
    text: str
    direction: Direction
    # IDs of evidence/signal records this point rests on. Validated after
    # generation: any ID the agent's tools never returned is stripped.
    evidence_ids: list[str] = Field(default_factory=list)

    # LLMs occasionally invent a label ("corporate"). Rejecting the whole
    # briefing over a label is worse than degrading it to the least-claiming
    # value, so unknown labels are coerced rather than fatal.
    @field_validator("theme", mode="before")
    @classmethod
    def _coerce_theme(cls, v):
        return v if v in _THEMES else "other"

    @field_validator("direction", mode="before")
    @classmethod
    def _coerce_direction(cls, v):
        return v if v in _DIRECTIONS else "neutral"


class Briefing(BaseModel):
    headline: str
    overall_tone: Direction
    points: list[BriefingPoint]
    conflicts: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    uncertainty: str

    @field_validator("overall_tone", mode="before")
    @classmethod
    def _coerce_tone(cls, v):
        return v if v in _DIRECTIONS else "neutral"
