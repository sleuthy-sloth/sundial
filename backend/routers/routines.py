"""Repeating blocks: the rule, and the days you decided something different.

Six routes, and two ideas behind them. Editing a routine changes every occurrence that has not
been touched — that is what a routine is for. Editing or skipping one day writes an override,
which is the only thing that can make one day differ, and the only thing the other five routes
do.

Every refusal here is a sentence. A routine that would end before it starts, a set of weekdays
that names no days, a day the rule does not reach: each is a 400 with something to read, because
the frontend has nowhere else to get those words from.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from clock import now_iso, today
from schemas.routines import OccurrencePatch, RoutineIn, RoutinePatch
from services import routines
from services.blocks import PALETTE
from services.routines import KINDS
from services.scheduling import check_fits, validate_day
from store import db

router = APIRouter()

# A rule, as stored. Kept apart from `routines.row_to_routine`, which is the same thing on the
# way out: what the API accepts and what it reports are one shape, and this is where they meet.
RULE_FIELDS = ("title", "start_min", "duration_min", "color", "icon", "notes",
               "recurrence_kind", "interval_weeks", "start_date", "end_date", "enabled")


def _rule(fields: dict, current: dict | None = None) -> dict:
    """The row as it will be, checked as a whole rather than as the fragment that arrived.

    The same reason `patch_block` judges the block it will be: a title and a colour sent in one
    request, or a start date moved past an end date that was already there, is only a mistake in
    the combination — and that is exactly what a per-field check cannot see.
    """
    rule = dict(current or {})
    rule.update(fields)

    title = str(rule.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "a routine needs a title")
    rule["title"] = title

    color = rule.get("color")
    if color is not None and color not in PALETTE:
        raise HTTPException(400, f"unknown color {color!r}")

    kind = rule.get("recurrence_kind")
    if kind not in KINDS:
        raise HTTPException(
            400,
            f"unknown repeat {kind!r} — it is one of {', '.join(KINDS)}",
        )

    days = rule.get("weekdays") or []
    # Accepts what the API takes (1..7) and what a hand-made file carries (the stored text), so a
    # patch straight off an export is not a special case.
    if isinstance(days, str):
        days = routines.parse_weekdays(days)
    bad = [d for d in days if not isinstance(d, int) or not 1 <= d <= 7]
    if bad:
        raise HTTPException(
            400, f"weekdays are days of the week, 1 (Monday) to 7 (Sunday); got {bad[0]!r}"
        )
    rule["weekdays"] = routines.weekdays_text(days)

    if kind == "selected_weekdays" and not rule["weekdays"]:
        raise HTTPException(400, "custom weekdays needs at least one day")

    start_date = rule.get("start_date") or today()
    validate_day(start_date)
    rule["start_date"] = start_date

    end_date = rule.get("end_date")
    if end_date is not None:
        validate_day(end_date)
        if end_date < start_date:
            raise HTTPException(400, "a routine cannot end before it starts")

    check_fits(int(rule["start_min"]), int(rule["duration_min"]))
    rule["enabled"] = bool(rule.get("enabled", True))
    rule["interval_weeks"] = int(rule.get("interval_weeks") or 1)
    return rule


@router.get("/api/routines")
def get_routines() -> dict:
    """Every routine, whether or not it has an occurrence today.

    A list of the rules is not a list of the day, and the two are asked for separately: the day
    view wants occurrences and the settings want rules, and neither wants the other's rows.
    """
    return {"routines": routines.list_routines()}


@router.post("/api/routines", status_code=201)
def create_routine(body: RoutineIn) -> dict:
    fields = body.model_dump()
    if fields.get("color") is None:
        fields["color"] = routines.pick_color()
    rule = _rule(fields)

    routine_id = uuid.uuid4().hex[:12]
    stamp = now_iso()
    with db() as conn:
        conn.execute(
            """INSERT INTO routines
                 (id, title, start_min, duration_min, color, icon, notes, recurrence_kind,
                  weekdays, interval_weeks, start_date, end_date, created_at, updated_at, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (routine_id, rule["title"], rule["start_min"], rule["duration_min"], rule["color"],
             str(rule.get("icon", "")).strip(), rule.get("notes", ""), rule["recurrence_kind"],
             rule["weekdays"], rule["interval_weeks"], rule["start_date"], rule["end_date"],
             stamp, stamp, int(rule["enabled"])),
        )
    return routines.get_routine(routine_id)


@router.patch("/api/routines/{routine_id}")
def patch_routine(routine_id: str, body: RoutinePatch) -> dict:
    """Change the rule. Every occurrence that has no override of its own changes with it.

    That is the deliberate half of the pair the UI offers. Editing a day writes an override and
    changes nothing else; editing the routine is the act that means "from now on".
    """
    current = routines.get_routine(routine_id)
    fields = body.model_dump(exclude_unset=True)

    # Only the end may be nulled. Everything else has a NOT NULL column behind it, and an
    # explicit null used to travel all the way to SQLite and come back as a 500.
    for key, value in fields.items():
        if value is None and key != "end_date":
            raise HTTPException(400, f"{key} cannot be null")

    rule = _rule(fields, current=current)
    if not fields:
        return current

    with db() as conn:
        conn.execute(
            """UPDATE routines
                  SET title = ?, start_min = ?, duration_min = ?, color = ?, icon = ?, notes = ?,
                      recurrence_kind = ?, weekdays = ?, interval_weeks = ?, start_date = ?,
                      end_date = ?, enabled = ?, updated_at = ?
                WHERE id = ?""",
            (rule["title"], rule["start_min"], rule["duration_min"], rule["color"],
             str(rule.get("icon", "")), rule.get("notes", ""), rule["recurrence_kind"],
             rule["weekdays"], rule["interval_weeks"], rule["start_date"], rule["end_date"],
             int(rule["enabled"]), now_iso(), routine_id),
        )
    return routines.get_routine(routine_id)


@router.delete("/api/routines/{routine_id}", status_code=204)
def delete_routine(routine_id: str) -> None:
    """Delete the rule and every override on it.

    The overrides go with it — `ON DELETE CASCADE`, with foreign keys on — because a day's
    opinion about a routine that no longer exists is not a thing anyone can ask about again.
    """
    with db() as conn:
        cur = conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such routine")


def _occurrence_day(routine: dict, day: str) -> None:
    """The day has to be one this rule reaches, or there is nothing to change.

    Not a 404: the routine is there. What is wrong is the request, and the sentence says which
    day of which thing was asked for — the alternative is an override row that no view will
    ever draw and no test will ever notice.
    """
    validate_day(day)
    if not routines.occurs_on(routine, day):
        raise HTTPException(
            400, f"{routine['title']} has no occurrence on {day} — the repeat does not reach it"
        )


def _view(routine: dict, day: str, override: dict | None) -> dict:
    """What one occurrence write answers with: the day as it now reads, or nothing.

    `occurrence` is null in exactly one case — you skipped it — and a null says that better than
    any state name would. The frontend reloads the day after every write; this is here so the
    answer is true on its own.
    """
    return {
        "routine_id": routine["id"],
        "day": day,
        "occurrence": routines.occurrence(routine, day, override),
    }


@router.post("/api/routines/{routine_id}/occurrences/{day}/skip")
def skip_occurrence(routine_id: str, day: str) -> dict:
    """Take one day out, and only that day.

    Nothing is deleted and nothing is regenerated: the rule still says Wednesday, and the
    override says not this Wednesday.
    """
    routine = routines.get_routine(routine_id)
    _occurrence_day(routine, day)
    with db() as conn:
        override = routines.set_override(
            conn, routine_id, day, uuid.uuid4().hex[:12], skipped=True
        )
    return _view(routine, day, override)


@router.patch("/api/routines/{routine_id}/occurrences/{day}")
def patch_occurrence(routine_id: str, day: str, body: OccurrencePatch) -> dict:
    """Change one day: the time it happens, the name it carries, whether it is done.

    Fields left out keep answering to the routine, which is what "edit this occurrence, not the
    routine" has to mean to be worth having. Sending `skipped: false` on a day you had taken out
    puts it back, and editing a skipped day puts it back too — you asked to change it, so it is
    there.
    """
    routine = routines.get_routine(routine_id)
    _occurrence_day(routine, day)
    fields = body.model_dump(exclude_unset=True)

    for key, value in fields.items():
        if value is None and key not in ("done", "skipped"):
            raise HTTPException(400, f"{key} cannot be null")

    if "title" in fields:
        fields["title"] = fields["title"].strip()
        if not fields["title"]:
            raise HTTPException(400, "a block needs a title")
    if "color" in fields and fields["color"] not in PALETTE:
        raise HTTPException(400, f"unknown color {fields['color']!r}")

    # Judged as it will be, like a block: a shorter length on an occurrence that already sits
    # late in the evening is only a mistake in the combination.
    with db() as conn:
        current = routines.get_override(conn, routine_id, day)
    start_min = fields.get("start_min", (current or {}).get("start_min") or routine["start_min"])
    duration = fields.get("duration_min", (current or {}).get("duration_min")
                          or routine["duration_min"])
    check_fits(start_min, duration)

    with db() as conn:
        override = routines.set_override(conn, routine_id, day, uuid.uuid4().hex[:12], **fields)
    return _view(routine, day, override)


@router.delete("/api/routines/{routine_id}/occurrences/{day}")
def reset_occurrence(routine_id: str, day: str) -> dict:
    """Put one day back to what the rule says.

    Not in the plan's list of suggested endpoints and deliberately added: "edit this occurrence"
    without "and undo that" is a door that only opens one way, and the person who moved the wrong
    day would have no way to say so.
    """
    routine = routines.get_routine(routine_id)
    _occurrence_day(routine, day)
    with db() as conn:
        dropped = routines.drop_override(conn, routine_id, day)
        if not dropped:
            raise HTTPException(404, f"nothing was ever changed about {day}")
    return _view(routine, day, None)
