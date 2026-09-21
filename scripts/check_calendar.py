#!/usr/bin/env python3
"""Check the calendar by hand, and optionally sync it.

    python scripts/check_calendar.py           connect, list the calendars, count the events
    python scripts/check_calendar.py --sync    do it for real, and say what changed
    python scripts/check_calendar.py --log     what the last few syncs decided

Run this after creating icloud.env (see docs/calendar-sync.md). It prints no credentials:
not the password, not the username, nothing that could end up in a screenshot. Exit codes
are meant for a timer: 0 fine, 1 not configured, 2 the server refused or was unreachable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import caldav  # noqa: E402
import calendar_service as service  # noqa: E402


def describe(credentials, session) -> int:
    print(f"  connecting to {credentials.endpoint}")
    calendars = session.calendars()
    if not calendars:
        print("  the server listed no calendars at all")
        return 2

    window_start = _window()[0]
    window_end = _window()[1]
    print(f"  {len(calendars)} calendar(s), window {window_start.date()} → {window_end.date()}:")
    for calendar in calendars:
        try:
            rows, cancelled = session.events(calendar["ref"], window_start, window_end)
        except caldav.CalDavError as exc:
            print(f"    {calendar['name']}: {exc}")
            continue
        marks = []
        if calendar["writable"]:
            marks.append("writable")
        if cancelled:
            marks.append(f"{len(cancelled)} cancelled")
        suffix = f" ({', '.join(marks)})" if marks else ""
        print(f"    {calendar['name']} [{calendar['colour']}]: {len(rows)} event(s){suffix}")
        for row in rows[:3]:
            print(f"        {row['start_utc']}  {row['title']}")
        if len(rows) > 3:
            print(f"        ... and {len(rows) - 3} more")
    return 0


def _window():
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc) - timedelta(days=service.WINDOW_BACK_DAYS)
    return start, start + timedelta(days=service.WINDOW_BACK_DAYS + service.WINDOW_FORWARD_DAYS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sync", action="store_true", help="store what is found, not just look")
    parser.add_argument("--log", action="store_true", help="print the last 20 sync decisions")
    args = parser.parse_args()

    if args.log:
        for entry in service.recent_log(20):
            print(f"  {entry['at']}  {entry['action']:9s} {entry['uid'] or '':<22s} {entry['detail']}")
        return 0

    credentials, why = service.configuration()
    if credentials is None:
        print(f"  not configured: {why}")
        print("  create icloud.env next to the app with ICLOUD_USERNAME and ICLOUD_APP_PASSWORD")
        return 1

    if not args.sync:
        try:
            with service.CalDavClient(credentials) as session:
                return describe(credentials, session)
        except caldav.CalDavError as exc:
            print(f"  could not read the calendar: {exc}")
            return 2

    print("  syncing")
    try:
        result = service.sync()
    except caldav.CalDavError as exc:
        print(f"  the sync could not run: {exc}")
        return 2

    for calendar in result["calendars"]:
        if calendar["error"]:
            print(f"    {calendar['name']}: {calendar['error']}")
        elif calendar["skipped"]:
            print(f"    {calendar['name']}: unchanged")
        else:
            print(
                f"    {calendar['name']}: {calendar['added']} new, {calendar['updated']} updated, "
                f"{calendar['removed']} removed, {calendar['unchanged']} unchanged"
            )
    totals = result["totals"]
    print(f"  totals: {totals}")
    return 2 if totals["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
