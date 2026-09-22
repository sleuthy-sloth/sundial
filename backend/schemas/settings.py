"""The request body for a setting, in the shape the routes and the published docs both read."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class SettingsPatch(BaseModel):
    """One or more settings, each stated as it should be.

    `extra="forbid"`, which is the opposite of the default and deliberate. A field this build does
    not know is a setting somebody else's build has, and accepting the request while dropping it
    would tell the caller their choice was saved when nothing was written. A refusal that names the
    field is the honest answer, and it is the same rule the import already follows for a column a
    table does not have.

    Which values are allowed is not stated here: it is asked of `services.settings`, so the words
    the API refuses with and the words it stores come from one place.
    """

    model_config = ConfigDict(extra="forbid")

    rollover: Optional[str] = None
