"""The request bodies for a template and its items, in the shape the routes read.

A template item is a block minus the two things a template cannot have: a day (given when the
template is applied) and a `done` flag (a template is a plan, not a record). Everything else is
the block's own shape, `start_min: null` included — which is the plan's "Anytime".
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from services.scheduling import DAY_MIN

# Long enough for "After the school run, before standup" and short enough to stay a name. The
# column has no limit; this is the API's, so a list stays readable.
NAME_MAX = 80


class TemplateSubtaskIn(BaseModel):
    """A line under an item: a name, and how long it is meant to take if you said.

    No hour and no colour. A line is inside its item: the item's `start_min` is when the task
    happens, and the item's colour is what the whole thing is drawn in. An hour here would be a
    second, contradicting answer to a question the item already answered.
    """

    title: str = Field(min_length=1, max_length=200)
    duration_min: int = Field(default=30, ge=5, le=DAY_MIN)


class TemplateItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    # Null means Anytime. Absolute minutes past midnight when it is there, the same units a
    # block's `start_min` is in, so applying is a copy and not a conversion.
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: int = Field(default=30, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: str = Field(default="", max_length=8)
    notes: str = ""
    # The checklist under this item, in the order it was written. One level: a line has no lines.
    subtasks: list[TemplateSubtaskIn] = Field(default_factory=list)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    # Items can arrive with the name: creating a template out of thin air and then editing it
    # would be two writes for one intention.
    items: list[TemplateItemIn] = Field(default_factory=list)


class TemplatePatch(BaseModel):
    """The name, and only the name.

    The items have a route of their own (`PUT /api/templates/{id}/blocks`) because they are
    replaced as a whole ordered list, and a patch that could do either would make "I renamed it"
    and "I rewrote it" the same request.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)


class TemplateItemsIn(BaseModel):
    """The whole list, in the order it should be read in. Absent means empty, not untouched."""

    items: list[TemplateItemIn] = Field(default_factory=list)


class DuplicateIn(BaseModel):
    """What to call the copy. Left out, the server names it after the original."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)


class ApplyIn(BaseModel):
    """The day to put it on. The template itself has no opinion about days."""

    day: str
