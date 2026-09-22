"""The app's own settings: what each one may be, and what it is right now.

One setting so far — `rollover`, which is what happens to unfinished scheduled work when the next
day is looked at. It is the first, so this module is written for the second one as well: a setting
is a name, the values it may hold, and the text it has while nobody has chosen.

The reason this is a table and a module rather than a `localStorage` key is the export. A setting
kept in a browser is absent from the file a person takes with them, absent from a backup, and reset
by every fresh install — and a setting that resets itself is worse than one that was never offered.
Anything that should follow the data has to be a row in the database, which is what the export
carries.

Stored as the text the API speaks, so a row reads in a SQLite browser and a refusal can name the
value it did not recognise. What a value may be is checked here rather than by a CHECK in SQL:
a CHECK in a key/value table has to name the key it belongs to, which is the coupling the shape
exists to avoid.
"""

from __future__ import annotations

from fastapi import HTTPException

from clock import now_iso
from store import db

# `rollover` — unfinished scheduled work, the next day. The order is the order the panel offers
# them in, and the first is the default: it is the only one of the three that changes nothing
# until you say so, which is the right thing for the app to do while nobody has chosen.
#
#     ask      list it on Today under one heading, and wait
#     anytime  move it to Anytime on sight
#     leave    do nothing at all; it stays on the day it was
ROLLOVER = ("ask", "anytime", "leave")

# Every setting and its allowed values. A name that is not in here is not a setting.
DEFAULTS: dict[str, tuple[str, ...]] = {"rollover": ROLLOVER}


def check(key: str, value) -> str:
    """A value as it will be stored, or a refusal with the value and the choices in it."""
    options = DEFAULTS.get(key)
    if options is None:
        raise HTTPException(400, f"unknown setting {key!r} — it is one of {', '.join(DEFAULTS)}")
    if value is None:
        raise HTTPException(400, f"{key} cannot be null")
    if value not in options:
        raise HTTPException(400, f"unknown {key} {value!r} — it is one of {', '.join(options)}")
    return value


def read() -> dict:
    """Every setting, with the ones nobody has chosen answered by their default.

    A fresh install has no rows at all and still answers, because "nothing stored" and "the
    default" are the same answer and the alternative is a route that 404s on a new database.

    A stored value the API would refuse — a row edited by hand, or an old build's — is answered
    with the default as well. There is nothing to be gained by reporting a value that every write
    of it would be refused with, and a reader should not have to know which builds wrote which.
    """
    with db() as conn:
        stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    return {
        name: stored.get(name) if stored.get(name) in options else options[0]
        for name, options in DEFAULTS.items()
    }


def write(key: str, value) -> dict:
    """Put one setting in place and answer with the whole set, the way a read would."""
    value = check(key, value)
    with db() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                             updated_at = excluded.updated_at""",
            (key, value, now_iso()),
        )
    return read()
