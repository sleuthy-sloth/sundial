"""The request bodies for a block, in the shape the routes and the published docs both read."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from services.scheduling import DAY_MIN


class BlockIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    day: Optional[str] = None
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: int = Field(default=30, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: str = Field(default="", max_length=8)
    notes: str = ""


class BlockPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    day: Optional[str] = None
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: Optional[int] = Field(default=None, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=8)
    notes: Optional[str] = None
    done: Optional[bool] = None
    unschedule: bool = False  # move the block back to the inbox
