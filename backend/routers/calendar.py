"""What is connected, what it holds, and the one route that accepts a secret.

Read-only in both directions that matter here: credentials go in and are answered with the
provider's state, and events come out. Nothing in this module writes to a calendar.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException

import calendar_service
import calendar_sync
import credentials
from caldav import NotConfigured
from calendar_errors import CalendarError
from clock import today
from schemas.calendar import CalendarPatch, CredentialsIn, SyncIn
from services.scheduling import validate_day
from store import db

router = APIRouter()


@router.get("/api/calendars")
def get_calendars() -> dict:
    """What is connected, and what is not — as a normal answer either way.

    An unconfigured calendar is not an error: it is the state a fresh install is in, and
    the interface should be able to say what to do about it instead of showing a failure.
    """
    state, why = calendar_service.configuration()
    providers = []
    for source in calendar_service.sources():
        entry = {
            "provider": source.provider,
            "configured": source.configured,
            "why": source.why,
            "last_error": calendar_service.provider_error(source.provider),
        }
        if source.provider == "google":
            entry["account"] = getattr(source.credentials, "account", "") if source.configured else ""
            # Built and tested end to end, and not switched on in the interface: the
            # credentials step cannot be walked until somebody has been through Google's
            # console, so the app says so rather than offering a button that fails.
            entry["coming_soon"] = True
        providers.append(entry)
    return {
        # Kept as the iCloud answer: it is what the rail's Sync control reads, and iCloud is
        # the provider that ships.
        "configured": state is not None,
        "why": why,
        "last_sync": calendar_service.last_sync(),
        "calendars": calendar_service.calendars(),
        "providers": providers,
    }


@router.post("/api/calendars/credentials")
def save_calendar_credentials(body: CredentialsIn) -> dict:
    """Take a credential from the panel and write it into that provider's file.

    The only route in sundial that accepts something secret that a person typed. It answers
    with the provider's state — never with what it was given — and it does not log: the value
    came from a form, and a form is not a reason for a secret to end up in a log file. Which
    keys are allowed, and why, is `credentials.py`.

    Read back rather than assumed: the reply says `configured` only if the provider's own
    reader agrees, so a write that landed somewhere useless cannot look like success.
    """
    try:
        target = credentials.save(body.provider, body.fields)
    except credentials.Refused as exc:
        raise HTTPException(400, str(exc)) from None

    source = next((s for s in calendar_service.sources() if s.provider == target.provider), None)
    return {
        "provider": target.provider,
        # `configured` and `why` come from the provider's own reader rather than from "the
        # write did not raise": for Google, credentials saved without a refresh token are
        # half a connection, and the reply has to be able to say which half is missing.
        "configured": bool(source and source.configured),
        "why": source.why if source else "",
    }


@router.post("/api/calendars/sync")
def sync_calendars(body: Optional[SyncIn] = None) -> dict:
    try:
        return calendar_service.sync(if_stale_seconds=(body or SyncIn()).if_stale_seconds)
    except NotConfigured as exc:
        raise HTTPException(400, str(exc)) from None
    except CalendarError as exc:
        # The sync could not start at all — bad credentials, no route, a server that
        # answered nonsense. A single calendar failing inside a working sync is reported
        # in the body instead, because the rest of the sync did happen.
        raise HTTPException(502, str(exc)) from None


@router.patch("/api/calendars")
def patch_calendar(body: CalendarPatch) -> dict:
    """Switch a calendar off, or back on. A local decision: it survives the next sync."""
    with db() as conn:
        changed = conn.execute(
            "UPDATE calendars SET enabled = ? WHERE ref = ?", (1 if body.enabled else 0, body.ref)
        ).rowcount
    if not changed:
        raise HTTPException(404, "no such calendar")
    return {"ref": body.ref, "enabled": body.enabled}


@router.get("/api/events")
def get_events(day: Optional[str] = None) -> dict:
    """The calendar's own events for one day, series expanded.

    A day rather than a range: this app's unit is the day, and the day is a wall-clock
    thing, so a caller does not get to send instants that disagree with it.
    """
    day = day or today()
    validate_day(day)
    zone = calendar_sync.server_tz()
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=zone)
    end = start + timedelta(days=1)
    events = calendar_service.events_between(start, end)
    return {"day": day, "count": len(events), "events": events}
