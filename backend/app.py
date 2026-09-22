"""The name the app is started by.

    uvicorn app:app --host 127.0.0.1 --port 6770 --app-dir backend

`deploy/sundial.service`, `run.sh` and the systemd unit check all start sundial by this name,
and five test modules import it, so the module stays and re-exports what they reach for. The
app itself is assembled in `main.py`; the database's shape is `bootstrap.py`; the block rules
are `services/`. Nothing lives here.

What is re-exported is wider than what a person would write today, and on purpose: a test
that monkeypatches `app.calendar_service.sync`, or reads `app.DB_PATH`, is patching the module
it named rather than the module that defines it, and that is the contract this file exists to
keep. `MIGRATIONS` is the exception — it is re-exported to be *read*, and `migrate()` reads
`bootstrap.MIGRATIONS`, so a test that wants a different migrations directory patches
`bootstrap`, which is where the runner lives.
"""

from __future__ import annotations

import calendar_service
import google_oauth
from bootstrap import MIGRATIONS, bootstrap, migrate
from caldav import CalDavError
from clock import today
from main import app
from services.blocks import PALETTE
from store import DB_PATH, db

__all__ = [
    "DB_PATH",
    "MIGRATIONS",
    "PALETTE",
    "CalDavError",
    "app",
    "bootstrap",
    "calendar_service",
    "db",
    "google_oauth",
    "migrate",
    "today",
]
