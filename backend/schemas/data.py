"""What a caller may send to replace everything."""

from __future__ import annotations

from pydantic import BaseModel


class ImportIn(BaseModel):
    """An import has to say what it is, because what it is is "replace everything"."""

    confirm: str = ""
    document: dict
