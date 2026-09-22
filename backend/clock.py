"""What the server thinks today is, and what it stamps a write with.

Small on purpose, and its own module because four routers and the export's filename all
need the same answer — the day is this app's unit, so "which day is it" is asked in more
places than anything else here.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timezone


def today() -> str:
    return _date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
