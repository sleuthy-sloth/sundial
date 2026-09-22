"""The app's own settings: read them, and change them.

Two routes, and neither of them is about the day — the setting they hold decides what the next day
does with the last one, and the answer to that is a row in the database so that it travels in an
export. No DELETE: a setting put back to its default is the default, and a route that removed the
row would be a second way to say the same thing.
"""

from __future__ import annotations

from fastapi import APIRouter

from schemas.settings import SettingsPatch
from services import settings

router = APIRouter()


@router.get("/api/settings")
def get_settings() -> dict:
    """Every setting, defaults included, so a caller never has to know them itself."""
    return settings.read()


@router.patch("/api/settings")
def patch_settings(body: SettingsPatch) -> dict:
    """Change the settings named in the body and leave the rest alone.

    One at a time is not worth a route per setting, and a partial body is what the other PATCHes
    here already take: what is named is stated as it should be, and what is absent is not a
    statement about anything.
    """
    changed = body.model_dump(exclude_unset=True)
    answer = settings.read()
    for key, value in changed.items():
        answer = settings.write(key, value)
    return answer
