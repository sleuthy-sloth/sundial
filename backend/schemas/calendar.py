"""What a caller may send about calendars, and the one body that carries a secret."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SyncIn(BaseModel):
    if_stale_seconds: int = Field(default=0, ge=0, le=86400)


class CalendarPatch(BaseModel):
    ref: str = Field(min_length=1, max_length=500)
    enabled: bool


class CredentialsIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    fields: dict[str, str] = Field(default_factory=dict)
