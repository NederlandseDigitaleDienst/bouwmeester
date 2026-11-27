"""Wensen voor Bouwmeester: suggesties en bugs per initiatief.

Een wens is een klein ticket: soort (suggestie of bug), titel, toelichting,
en wie hem wanneer meldde. De lijst staat als JSON op het initiatief
(initiatief.wensen) en wordt in zijn geheel opgeslagen.
"""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Wens(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=64)
    soort: Literal["suggestie", "bug"] = "suggestie"
    titel: str = Field(min_length=1, max_length=300)
    # Rich text, zoals een toelichting elders.
    toelichting: str | None = Field(None, max_length=5000)
    gemeld_door: str | None = Field(None, max_length=200)
    gemeld_op: date | None = None

    @field_validator("titel", mode="before")
    @classmethod
    def _strip_titel(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("toelichting", "gemeld_door", mode="before")
    @classmethod
    def _leeg_is_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v
