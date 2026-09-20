"""The cases calendar code rots on: DST, all-day, multi-day, cancelled, and a series
that has to keep its local hour. Fixtures are inline ICS — real payloads, no network."""

from datetime import datetime, timezone

import pytest

import calendar_sync as cs


def ics(body: str) -> str:
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{body}\r\nEND:VCALENDAR\r\n"


TIMED = ics(
    "BEGIN:VEVENT\r\n"
    "UID:dentist-1\r\n"
    "SUMMARY:Dentist\r\n"
    "DTSTART;TZID=America/Los_Angeles:20260921T140000\r\n"
    "DTEND;TZID=America/Los_Angeles:20260921T150000\r\n"
    "LOCATION:123 Main St\r\n"
    "END:VEVENT"
)

ALL_DAY = ics(
    "BEGIN:VEVENT\r\n"
    "UID:holiday-1\r\n"
    "SUMMARY:Day off\r\n"
    "DTSTART;VALUE=DATE:20260921\r\n"
    "DTEND;VALUE=DATE:20260922\r\n"
    "END:VEVENT"
)

MULTI_DAY = ics(
    "BEGIN:VEVENT\r\n"
    "UID:trip-1\r\n"
    "SUMMARY:Conference\r\n"
    "DTSTART:20260921T090000Z\r\n"
    "DTEND:20260923T170000Z\r\n"
    "END:VEVENT"
)

CANCELLED = ics(
    "BEGIN:VEVENT\r\nUID:gone-1\r\nSUMMARY:Cancelled thing\r\nSTATUS:CANCELLED\r\n"
    "DTSTART:20260921T090000Z\r\nDTEND:20260921T100000Z\r\nEND:VEVENT"
)

# Two mornings either side of the DST change (US DST ends 2026-11-01). Same wall
# clock, different instants — which is the whole reason events are stored as instants.
BEFORE_AND_AFTER_DST = ics(
    "BEGIN:VEVENT\r\nUID:sat-1\r\nSUMMARY:Saturday\r\n"
    "DTSTART;TZID=America/Los_Angeles:20261031T090000\r\n"
    "DTEND;TZID=America/Los_Angeles:20261031T100000\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:mon-1\r\nSUMMARY:Monday\r\n"
    "DTSTART;TZID=America/Los_Angeles:20261102T090000\r\n"
    "DTEND;TZID=America/Los_Angeles:20261102T100000\r\nEND:VEVENT"
)

WEEKLY_ACROSS_DST = ics(
    "BEGIN:VEVENT\r\n"
    "UID:weekly-1\r\n"
    "SUMMARY:Weekly review\r\n"
    "DTSTART;TZID=America/Los_Angeles:20261026T090000\r\n"
    "DTEND;TZID=America/Los_Angeles:20261026T093000\r\n"
    "RRULE:FREQ=WEEKLY\r\n"
    "END:VEVENT"
)


def rows(text, ref="cal-1", provider="icloud"):
    parsed, cancelled = cs.events_from_ics(text, ref, provider, now="2026-09-20T00:00:00+00:00")
    return parsed, cancelled


# ---- reading ----


def test_a_timed_event_is_stored_as_an_instant():
    parsed, _ = rows(TIMED)
    assert len(parsed) == 1
    row = parsed[0]
    # 14:00 in Los Angeles on 2026-09-21 is 21:00 UTC (PDT, UTC-7).
    assert row["start_utc"] == "2026-09-21T21:00:00+00:00"
    assert row["end_utc"] == "2026-09-21T22:00:00+00:00"
    assert row["all_day"] == 0
    assert row["title"] == "Dentist"
    assert row["location"] == "123 Main St"
    assert row["uid"] == "dentist-1"


def test_the_same_wall_clock_time_is_a_different_instant_across_dst():
    parsed, _ = rows(BEFORE_AND_AFTER_DST)
    by_uid = {row["uid"]: row for row in parsed}
    assert by_uid["sat-1"]["start_utc"] == "2026-10-31T16:00:00+00:00"  # PDT, UTC-7
    assert by_uid["mon-1"]["start_utc"] == "2026-11-02T17:00:00+00:00"  # PST, UTC-8


def test_an_all_day_event_is_flagged_and_spans_a_day():
    parsed, _ = rows(ALL_DAY)
    row = parsed[0]
    assert row["all_day"] == 1
    assert row["start_utc"] == "2026-09-21T00:00:00+00:00"
    assert row["end_utc"] == "2026-09-22T00:00:00+00:00"


def test_a_multi_day_event_keeps_its_span():
    parsed, _ = rows(MULTI_DAY)
    row = parsed[0]
    start = datetime.fromisoformat(row["start_utc"])
    end = datetime.fromisoformat(row["end_utc"])
    assert (end - start).days == 2 and (end - start).seconds == 8 * 3600


def test_a_cancelled_event_is_an_instruction_not_a_row():
    parsed, cancelled = rows(CANCELLED)
    assert parsed == []
    assert cancelled == ["gone-1"]


def test_a_series_is_stored_once_with_what_it_needs_to_expand():
    parsed, _ = rows(WEEKLY_ACROSS_DST)
    assert len(parsed) == 1
    assert parsed[0]["rrule"] == "FREQ=WEEKLY"
    assert "RRULE:FREQ=WEEKLY" in parsed[0]["raw_ics"]


def test_expanding_a_series_keeps_its_local_hour_across_dst():
    """A weekly 09:00 must stay 09:00 after the clocks change."""
    row, _ = rows(WEEKLY_ACROSS_DST)
    occurrences = cs.expand_series(
        row[0],
        datetime(2026, 10, 26, tzinfo=timezone.utc),
        datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    assert len(occurrences) == 2
    assert [o["start_utc"] for o in occurrences] == [
        "2026-10-26T16:00:00+00:00",  # 09:00 PDT
        "2026-11-02T17:00:00+00:00",  # 09:00 PST
    ]


def test_expanding_something_that_is_not_a_series_is_a_no_op():
    row, _ = rows(TIMED)
    assert cs.expand_series(row[0], datetime(2026, 1, 1), datetime(2027, 1, 1)) == [row[0]]


# ---- writing ----


def test_a_block_becomes_a_vevent_and_comes_back_intact():
    block = {
        "id": "abc123",
        "title": "Deep work, with a comma",
        "day": "2026-09-21",
        "start_min": 9 * 60,
        "duration_min": 90,
        "notes": "notes with an emoji 🧘",
    }
    # The timezone is passed explicitly: the default is the machine's own zone, and
    # this test must not depend on where it runs.
    written = cs.block_to_ics(block, tzid="America/Los_Angeles").decode()
    back, _ = cs.events_from_ics(written, "sundial", "icloud")
    assert len(back) == 1
    assert back[0]["uid"] == "abc123@sundial"
    assert back[0]["title"] == "Deep work, with a comma"
    assert back[0]["notes"] == "notes with an emoji 🧘"
    assert back[0]["start_utc"] == "2026-09-21T16:00:00+00:00"  # 09:00 PDT
    assert back[0]["end_utc"] == "2026-09-21T17:30:00+00:00"


def test_an_unscheduled_block_has_no_event_to_write():
    with pytest.raises(ValueError, match="only a scheduled block"):
        cs.block_to_ics({"id": "x", "title": "inbox", "day": None, "start_min": None, "duration_min": 30})


def test_the_uid_is_stable_so_a_push_updates_rather_than_duplicates():
    block = {"id": "same", "title": "one", "day": "2026-09-21", "start_min": 60, "duration_min": 30}
    first, _ = cs.events_from_ics(cs.block_to_ics(block, tzid="UTC").decode(), "s", "icloud")
    block["title"] = "changed"
    second, _ = cs.events_from_ics(cs.block_to_ics(block, tzid="UTC").decode(), "s", "icloud")
    assert first[0]["uid"] == second[0]["uid"] == "same@sundial"


# ---- conflicts ----


def local(sequence=0, updated="2026-09-20T00:00:00+00:00", **extra):
    return {"sequence": sequence, "updated_at": updated, "title": "local", "color": "emerald",
            "done": 0, "etag": "e1", **extra}


def test_a_higher_sequence_remote_wins():
    remote = local(sequence=2, updated="2026-09-19T00:00:00+00:00", title="remote")
    keep = local(sequence=1)
    assert cs.remote_wins(keep, remote) is True
    merged = cs.merge_remote(keep, remote)
    assert merged["title"] == "remote"


def test_an_older_remote_loses_to_a_local_edit():
    remote = local(sequence=1, updated="2026-09-19T00:00:00+00:00", title="remote")
    keep = local(sequence=1, updated="2026-09-20T12:00:00+00:00")
    assert cs.remote_wins(keep, remote) is False
    merged = cs.merge_remote(keep, remote)
    assert merged["title"] == "local"
    assert merged["etag"] == "e1"  # bookkeeping still refreshes, so the next sync is quiet


def test_a_remote_change_never_touches_colour_or_done():
    remote = local(sequence=9, updated="2026-09-21T00:00:00+00:00", title="remote",
                   color="rose", done=1)
    merged = cs.merge_remote(local(sequence=1), remote)
    assert merged["title"] == "remote"
    assert merged["color"] == "emerald"
    assert merged["done"] == 0


def test_an_unseen_event_is_taken_as_is():
    remote = local(title="new")
    assert cs.merge_remote(None, remote) == remote
