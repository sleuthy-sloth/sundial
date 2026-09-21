"""Today's plan as a Cadu card payload — the glanceable version of the day view.

    python3 scripts/cadu_card.py                      # today, from the running app
    python3 scripts/cadu_card.py --day 2026-09-24      # another day
    python3 scripts/cadu_card.py --url http://127.0.0.1:6799
    python3 scripts/cadu_card.py --at 14:30            # pretend it is half past two

Prints one JSON object: the payload for Cadu's `cadu_present_card`, type `checklist`. It reads
the app's own API rather than the database, so it works against a running copy from anywhere
and cannot disagree with what the day view shows.

Why a checklist and not a chart. A bar chart of the day's durations is prettier and tells you
nothing you cannot see at a glance; the question a phone is answering is "what am I supposed to
be doing, and what is next", which is a list of things with ticks beside them.

Two honesties are built in:

* `completed` comes from the block's own `done` flag, never from the clock. Marking a block that
  has merely gone by as done would be the card telling a comfortable lie about a day that did
  not happen — and nothing downstream would ever contradict it.
* Ticking an item in Cadu is saved on the phone and is never reported back to sundial. The card
  says so in its own summary, because the alternative is a person believing they have updated
  their plan.

Standard library only, like the rest of `scripts/`: this has to run whether or not the app's
dependencies are importable.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date as _date
from datetime import datetime
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:6770"
MAX_ITEMS = 40  # the card's own limit, and the reason the summary counts what it trimmed
NOT_SYNCED = "Ticking an item here is kept on your phone and does not change sundial."


def clock(minutes: int) -> str:
    """540 -> "09:00". Minutes past midnight, as the app stores them."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def span(block: dict) -> str:
    """The hours a block occupies, as the day view draws them."""
    start = block["start_min"]
    return f"{clock(start)}–{clock(start + block['duration_min'])}"


def length(minutes: int) -> str:
    """A duration in the terms a person says it: "45m", "1h", "1h 30m"."""
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"


def day_label(day: str, today: str) -> str:
    """"Today", or the date spelled out when it is not."""
    if day == today:
        return "Today"
    try:
        when = _date.fromisoformat(day)
    except ValueError:
        return day
    return when.strftime("%a %-d %b")


def payload(document: dict, now: datetime) -> dict:
    """The card, from one day's worth of the API's answer."""
    day = document["day"]
    scheduled = [b for b in document.get("blocks", []) if b.get("start_min") is not None]
    inbox = [b for b in document.get("inbox", [])]
    today = document.get("today", day)
    now_minutes = now.hour * 60 + now.minute

    items = [
        {
            "id": block["id"],
            "title": block["title"][:160],
            "detail": f"{span(block)} · {length(block['duration_min'])}",
            # The block's own answer, never the clock's.
            "completed": bool(block.get("done")),
        }
        for block in scheduled
    ]
    for block in inbox:
        items.append(
            {
                "id": block["id"],
                "title": block["title"][:160],
                "detail": "anytime",
                "completed": bool(block.get("done")),
            }
        )
    trimmed = max(0, len(items) - MAX_ITEMS)
    items = items[:MAX_ITEMS]

    planned = sum(b["duration_min"] for b in scheduled)
    headline = [
        f"{len(scheduled)} block{'' if len(scheduled) == 1 else 's'}" if scheduled else "no blocks",
        length(planned) if planned else "",
        f"{len(inbox)} in the inbox" if inbox else "",
    ]
    title = f"{day_label(day, today)} — " + ", ".join(part for part in headline if part)

    return {
        "version": 1,
        "type": "checklist",
        # Required, and only the real validator says so: a checklist is an interactive card, and
        # "Card data must contain exactly: version, type, id, title, summary, checklist" is what
        # came back the first time one was sent without it. Stable per day so a re-render of the
        # same plan is the same card.
        "id": f"sundial-plan-{day}",
        "title": title[:120],
        "summary": summary(day, today, scheduled, inbox, items, now_minutes, trimmed),
        "checklist": {"items": items},
    }


def summary(
    day: str,
    today: str,
    scheduled: list[dict],
    inbox: list[dict],
    items: list[dict],
    now_minutes: int,
    trimmed: int,
) -> str:
    """What is happening now, what is next, and the one thing the card cannot do.

    Written as sentences rather than a restatement of the list below it: the card already shows
    the blocks, so this says the part that takes reading to work out.
    """
    parts: list[str] = []
    if not scheduled and not inbox:
        parts.append("Nothing planned.")
    elif day != today:
        parts.append(f"{len(scheduled)} block(s) planned." if scheduled else "Nothing scheduled.")
    else:
        current = next(
            (
                b
                for b in scheduled
                if b["start_min"] <= now_minutes < b["start_min"] + b["duration_min"]
            ),
            None,
        )
        following = next((b for b in scheduled if b["start_min"] > now_minutes), None)
        if current:
            ends = current["start_min"] + current["duration_min"]
            parts.append(f"Now: {current['title']}, until {clock(ends)}.")
        if following:
            lead = "Next" if current else "Next up"
            parts.append(f"{lead}: {following['title']} at {clock(following['start_min'])}.")
        elif scheduled and not current:
            last = scheduled[-1]
            ends = last["start_min"] + last["duration_min"]
            if now_minutes >= ends:
                parts.append(f"The day is behind you — the last block ended at {clock(ends)}.")
    if trimmed:
        parts.append(f"{trimmed} more did not fit on the card.")
    parts.append(NOT_SYNCED)
    return " ".join(parts)[:600]


def fetch(url: str, day: str, timeout: float = 10.0) -> dict:
    """One day from the running app. A refusal is the app's own sentence, not a stack trace."""
    target = f"{url.rstrip('/')}/api/day?day={day}"
    try:
        with urllib.request.urlopen(target, timeout=timeout) as answer:
            return json.loads(answer.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()
        raise SystemExit(f"{target}: {exc.code} {detail}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"could not reach sundial at {url} ({exc.reason}). Is it running?"
        ) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print today's plan as a Cadu checklist card payload."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="where sundial is answering")
    parser.add_argument("--day", default=None, help="YYYY-MM-DD, default today")
    parser.add_argument("--at", default=None, help="HH:MM, what to treat as now")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON")
    args = parser.parse_args(argv)

    now = datetime.now()
    if args.at:
        try:
            hour, minute = (int(part) for part in args.at.split(":", 1))
            now = now.replace(hour=hour, minute=minute)
        except ValueError:
            raise SystemExit(f"--at wants HH:MM, not {args.at!r}") from None

    document = fetch(args.url, args.day or _date.today().isoformat())
    card = payload(document, now)
    print(json.dumps(card, indent=2 if args.pretty else None, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
