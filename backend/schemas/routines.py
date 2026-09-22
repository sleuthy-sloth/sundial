"""The request bodies for a routine, in the shape the routes and the published docs both read.

`weekdays` is a list of ISO numbers — 1 is Monday, 7 is Sunday — rather than the string the
database stores. A set of days is an array in JSON, and asking the client to build the storage
form would put a piece of this app's storage in the client.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from services.scheduling import DAY_MIN


class RoutineIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_min: int = Field(ge=0, lt=DAY_MIN)
    duration_min: int = Field(default=30, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: str = Field(default="", max_length=8)
    notes: str = ""
    recurrence_kind: str
    weekdays: list[int] = Field(default_factory=list)
    interval_weeks: int = Field(default=1, ge=1, le=52)
    # The day the rule starts counting from, and the day it stops. Left out, it starts today.
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    enabled: bool = True


class RoutinePatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: Optional[int] = Field(default=None, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=8)
    notes: Optional[str] = None
    recurrence_kind: Optional[str] = None
    weekdays: Optional[list[int]] = None
    interval_weeks: Optional[int] = Field(default=None, ge=1, le=52)
    start_date: Optional[str] = None
    # `end_date: null` means "and it never ends", which is a value rather than an absence, so
    # this is the one field a routine may be sent a null for.
    end_date: Optional[str] = None
    enabled: Optional[bool] = None


class OccurrencePatch(BaseModel):
    """One day's worth of disagreement with the rule.

    Every field is optional and an absent one means "as the routine says" — which is what makes
    an override a patch rather than a copy, and why renaming a routine still renames every day
    you never touched.

    `done` and `skipped` are stated rather than derived: they are what you decided about this
    day, not fields of the block.
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: Optional[int] = Field(default=None, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=8)
    notes: Optional[str] = None
    done: Optional[bool] = None
    skipped: Optional[bool] = None
