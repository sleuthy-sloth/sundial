"""What a day is made of: the week's own arithmetic, and the numbers it reports.

The week is a capacity reading — planned, open, and the calendar's own busy time — so the thing
worth locking down is the union. Every figure here counts a minute once: two blocks that overlap
are not two hours of your life, a block nested inside another does not invent free time behind
it, and an appointment sharing an hour with a block does not make that hour free twice over.

The cases the plan names are all here: overlap maths, calendar overlap maths, an empty day, a
full day, a week that crosses a month and a year boundary. The rest are the edges that fall out
of those — a block running in from yesterday, an all-day event, a calendar switched off, an
inbox item that belongs to no day at all.

`/api/week` also keeps the `blocks` and `minutes` it has always answered with, because the strip
that reads them predates this. The one that matters: `minutes` sums the durations and so
over-states an overlapping day, while `planned_minutes` does not. That disagreement is asserted
rather than smoothed over — it is the bug this route was carrying.

Run with:  cd backend && .venv/bin/pytest -q
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app
import calendar_sync
import store
from services.scheduling import day_stats, merge_spans, union_minutes

MONDAY = "2026-09-21"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    """The zone this file's instants are read in, and the cache dropped either side of a test.

    `calendar_sync.server_tz` is cached for the process and answers with the machine's own zone
    unless `SUNDIAL_TZ` says otherwise — so without this, an instant's hour here would be a fact
    about which test module ran first rather than about this one.
    """
    monkeypatch.setenv("SUNDIAL_TZ", "UTC")
    calendar_sync.server_tz.cache_clear()
    yield
    calendar_sync.server_tz.cache_clear()


@pytest.fixture
def client(database):
    """The real app over the test's database."""
    return TestClient(app.app)


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "sundial.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    app.bootstrap()
    return path


def schedule(client, day=MONDAY, start_min=540, duration_min=30, **kw):
    body = {"title": "thing", "day": day, "start_min": start_min, "duration_min": duration_min, **kw}
    res = client.post("/api/blocks", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def add_calendar(ref="/home/", enabled=1):
    with store.db() as conn:
        conn.execute(
            """INSERT INTO calendars (ref, provider, name, colour, enabled, writable, ctag, last_sync)
               VALUES (?, 'icloud', 'Home', 'sky', ?, 0, 'ctag-1', '2026-09-01T00:00:00+00:00')""",
            (ref, enabled),
        )


def add_event(start, end, all_day=0, ref="/home/", uid="e1", title="Dentist", rrule=None):
    """An event as the sync stores one: instants, and a flag for the ones that are a date."""
    with store.db() as conn:
        conn.execute(
            """INSERT INTO events (id, calendar_ref, provider, uid, recurrence_id, title, location,
                 notes, start_utc, end_utc, all_day, rrule, raw_ics, status, etag, sequence, updated_at)
               VALUES (?, ?, 'icloud', ?, '', ?, '', '', ?, ?, ?, ?, NULL, 'CONFIRMED', 'e', 0, ?)""",
            (
                f"{ref}|{uid}|",
                ref,
                uid,
                title,
                start.isoformat(),
                end.isoformat(),
                all_day,
                rrule,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )


def at(hour, minute=0, day=MONDAY):
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00+00:00")


def week(client, start=MONDAY, days=7):
    res = client.get(f"/api/week?start={start}&days={days}")
    assert res.status_code == 200, res.text
    return {d["day"]: d for d in res.json()["days"]}


# ---- the union, on its own ------------------------------------------------------------------


def test_a_nested_block_does_not_invent_free_time_behind_it():
    # 09:00+120min, and 09:30+30min sitting inside it. Comparing each block with the one before
    # it sees this as two stretches and a gap; there is no gap.
    assert merge_spans([(540, 660), (570, 600)]) == [(540, 660)]
    assert union_minutes([(540, 660), (570, 600)]) == 120


def test_spans_that_only_touch_are_one_stretch():
    # 09:00–10:00 and 10:00–11:00 is a morning, not two. The frontend merges on the same rule.
    assert merge_spans([(540, 600), (600, 660)]) == [(540, 660)]
    assert union_minutes([(540, 600), (600, 660)]) == 120


def test_the_same_two_blocks_out_of_order_still_merge():
    assert merge_spans([(570, 600), (540, 660)]) == [(540, 660)]


def test_spans_that_do_not_meet_stay_two_and_keep_the_gap():
    assert merge_spans([(540, 600), (630, 660)]) == [(540, 600), (630, 660)]
    assert union_minutes([(540, 600), (630, 660)]) == 90


def test_an_empty_span_and_a_nonsense_one_are_ignored_rather_than_raised_on():
    # Pure, so it answers instead of refusing: nothing here is a rule about a request.
    assert merge_spans([]) == []
    assert union_minutes([(600, 600), (660, 600)]) == 0


def test_the_worked_example_from_the_plan():
    # 09:00+90m, 10:00+60m, 10:30+15m: 165 minutes if you sum them, 120 if you merge them.
    blocks = [
        {"start_min": 540, "duration_min": 90},
        {"start_min": 600, "duration_min": 60},
        {"start_min": 630, "duration_min": 15},
    ]
    assert union_minutes([(b["start_min"], b["start_min"] + b["duration_min"]) for b in blocks]) == 120


# ---- the route: the plan's half ------------------------------------------------------------


def test_an_empty_day_is_empty_rather_than_absent(client):
    day = week(client)[MONDAY]
    assert day["blocks"] == 0 and day["minutes"] == 0
    assert day["planned_minutes"] == 0
    assert day["open_minutes"] == 1440
    assert day["block_count"] == 0 and day["completed_count"] == 0
    assert day["calendar_busy_minutes"] == 0


def test_overlapping_blocks_are_counted_once_and_the_old_sum_still_says_otherwise(client):
    schedule(client, start_min=540, duration_min=90)
    schedule(client, start_min=600, duration_min=60)
    schedule(client, start_min=630, duration_min=15)

    day = week(client)[MONDAY]
    assert day["planned_minutes"] == 120
    assert day["open_minutes"] == 1440 - 120
    assert day["block_count"] == 3
    # The shape this route already answered with, unchanged: three durations added up. It is
    # the number the strip was drawn from, and it is 37.5% more than the day actually holds.
    assert day["minutes"] == 165
    assert day["blocks"] == day["block_count"] == 3


def test_a_full_day_has_nothing_open(client):
    # Four six-hour blocks that meet end to end: one twenty-four hour stretch, and the last
    # one ends exactly at midnight, which is the edge `check_fits` allows.
    for start in (0, 360, 720, 1080):
        schedule(client, start_min=start, duration_min=360)

    day = week(client)[MONDAY]
    assert day["planned_minutes"] == 1440
    assert day["open_minutes"] == 0
    assert day["blocks"] == 4


def test_completed_blocks_are_still_time_spent(client):
    first = schedule(client, start_min=540, duration_min=60)
    schedule(client, start_min=600, duration_min=60)
    client.patch(f"/api/blocks/{first['id']}", json={"done": True})

    day = week(client)[MONDAY]
    assert day["planned_minutes"] == 120, "a finished block is not room to fill"
    assert day["completed_count"] == 1
    assert day["block_count"] == 2


def test_an_inbox_item_belongs_to_no_day(client):
    schedule(client, start_min=540, duration_min=60)
    res = client.post("/api/blocks", json={"title": "someday", "duration_min": 60})
    assert res.status_code == 201

    day = week(client)[MONDAY]
    assert day["planned_minutes"] == 60 and day["block_count"] == 1


def test_a_week_that_crosses_a_month_and_a_year_still_lists_every_day(client):
    span = client.get("/api/week?start=2026-12-28&days=7").json()["days"]
    assert [d["day"] for d in span] == [
        "2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03",
    ]
    # And a block in the new year lands on the new year's day, in the same answer.
    schedule(client, day="2027-01-01", start_min=0, duration_min=60)
    span = week(client, start="2026-12-28")
    assert span["2026-12-31"]["planned_minutes"] == 0
    assert span["2027-01-01"]["planned_minutes"] == 60
    assert span["2027-01-01"]["open_minutes"] == 1380


def test_a_day_routine_counts_towards_the_week(client):
    # The week and the day must not disagree: a routine is on Monday's page, so it is on
    # Monday's bar. The occurrence has no row, which is exactly why this is worth asserting.
    res = client.post(
        "/api/routines",
        json={
            "title": "Gym", "start_min": 390, "duration_min": 60, "color": "emerald",
            "recurrence_kind": "weekdays", "start_date": MONDAY,
        },
    )
    assert res.status_code == 201, res.text

    span = week(client)
    assert span[MONDAY]["planned_minutes"] == 60 and span[MONDAY]["block_count"] == 1
    assert span[MONDAY]["minutes"] == 60
    # Saturday is not a weekday, so the rule reaches no further than the days it names.
    assert span["2026-09-26"]["planned_minutes"] == 0


# ---- the route: the calendar's half --------------------------------------------------------


def test_an_event_takes_the_hour_the_day_keeps_not_the_utc_one(client):
    add_calendar()
    # 14:00 local, stored as the instant it is.
    add_event(at(14), at(15))

    day = week(client)[MONDAY]
    assert day["calendar_busy_minutes"] == 60
    assert day["open_minutes"] == 1380
    assert day["planned_minutes"] == 0


def test_an_event_and_a_block_that_share_an_hour_cost_that_hour_once(client):
    add_calendar()
    add_event(at(14), at(15))
    schedule(client, start_min=14 * 60 + 30, duration_min=60)  # 14:30–15:30

    day = week(client)[MONDAY]
    assert day["calendar_busy_minutes"] == 60
    assert day["planned_minutes"] == 60
    # Not 1440 - 60 - 60 = 1320: half an hour of that is one half hour.
    assert day["open_minutes"] == 1440 - 90


def test_two_overlapping_events_are_counted_once(client):
    add_calendar()
    add_event(at(9), at(11), uid="a")
    add_event(at(10), at(12), uid="b")

    assert week(client)[MONDAY]["calendar_busy_minutes"] == 180


def test_a_calendar_switched_off_contributes_nothing(client):
    add_calendar(ref="/home/", enabled=0)
    add_event(at(14), at(15))

    day = week(client)[MONDAY]
    assert day["calendar_busy_minutes"] == 0 and day["open_minutes"] == 1440


def test_an_appointment_running_in_from_last_night_clamps_to_midnight(client):
    add_calendar()
    add_event(datetime.fromisoformat("2026-09-20T23:00:00+00:00"), at(1))

    # One hour that straddles midnight is an hour on each of the two days it is in: an hour of
    # Sunday evening and an hour of Monday, and neither of them runs to 25:00.
    span = week(client, start="2026-09-20")
    assert span["2026-09-20"]["calendar_busy_minutes"] == 60
    assert span[MONDAY]["calendar_busy_minutes"] == 60
    assert span[MONDAY]["open_minutes"] == 1380


def test_an_all_day_event_takes_the_whole_day_it_is_dated(client):
    add_calendar()
    add_event(at(0, day="2026-09-22"), at(0, day="2026-09-23"), all_day=1, title="Bank holiday")

    span = week(client)
    assert span["2026-09-22"]["calendar_busy_minutes"] == 1440
    assert span["2026-09-22"]["open_minutes"] == 0
    assert span[MONDAY]["calendar_busy_minutes"] == 0


def test_an_event_stored_with_an_unreadable_instant_costs_only_itself(client):
    add_calendar()
    add_event(at(9), at(10), uid="good")
    add_event(datetime.fromisoformat("2026-09-21T09:00:00+00:00"), at(10), uid="bad")
    with store.db() as conn:
        conn.execute("UPDATE events SET end_utc = 'yesterdayish' WHERE uid = 'bad'")

    # One bad row is one event missing, not a week that cannot be read.
    assert client.get(f"/api/week?start={MONDAY}").status_code == 200
    assert week(client)[MONDAY]["calendar_busy_minutes"] == 60


# ---- the shapes a screen reads --------------------------------------------------------------


def test_every_day_in_the_answer_carries_the_same_fields(client):
    schedule(client)
    for day in week(client).values():
        assert set(day) == {
            "day", "blocks", "minutes", "planned_minutes", "open_minutes",
            "block_count", "completed_count", "calendar_busy_minutes",
        }


def test_a_day_that_cannot_be_read_still_answers_as_a_day():
    # day_stats is pure and its caller has a sentence for a bad range; nothing in it raises.
    assert day_stats(MONDAY, [], [], timezone.utc) == {
        "day": MONDAY,
        "planned_minutes": 0,
        "open_minutes": 1440,
        "block_count": 0,
        "completed_count": 0,
        "calendar_busy_minutes": 0,
    }


def test_the_zone_the_day_is_measured_in_is_the_one_the_events_land_in(client, monkeypatch):
    # The same stored instant is a different hour of a different day depending on where the day
    # is lived. 02:00 UTC is 19:00 the evening before in Los Angeles, so in that zone the event
    # is not on Monday at all — and a week that placed it by its UTC hour would say it was.
    add_calendar()
    add_event(at(2), at(3), uid="early")
    assert week(client)[MONDAY]["calendar_busy_minutes"] == 60

    monkeypatch.setenv("SUNDIAL_TZ", "America/Los_Angeles")
    calendar_sync.server_tz.cache_clear()  # the zone is cached; the environment it is read from is not
    span = week(client, start="2026-09-20")
    assert span[MONDAY]["calendar_busy_minutes"] == 0
    assert span["2026-09-20"]["calendar_busy_minutes"] == 60

    # And the query window moved with the zone, rather than the event being fetched for one
    # definition of a day and placed by another: asked for in UTC, it is on Monday.
    monkeypatch.setenv("SUNDIAL_TZ", "UTC")
    calendar_sync.server_tz.cache_clear()
    assert week(client)[MONDAY]["calendar_busy_minutes"] == 60


def test_a_week_is_still_bounded_and_validated(client):
    assert len(client.get("/api/week?days=999").json()["days"]) == 31
    assert len(client.get("/api/week?days=0").json()["days"]) == 1
    assert client.get("/api/week?start=nope").status_code == 400
    assert client.get("/api/week?start=9999-12-31&days=31").status_code == 400
    # The last day on the calendar is a day like any other: there is no tomorrow to end its
    # window at, and that is not a reason to refuse the week.
    last = client.get("/api/week?start=9999-12-31&days=1")
    assert last.status_code == 200, last.text
    assert last.json()["days"][0]["open_minutes"] == 1440


def test_an_event_outside_the_week_asked_for_is_not_in_its_answer(client):
    add_calendar()
    add_event(at(14), at(15), uid="this-week")
    add_event(at(14, day="2026-11-14"), at(15, day="2026-11-14"), uid="next-month")

    assert week(client)[MONDAY]["calendar_busy_minutes"] == 60
    assert week(client, start="2026-11-14")["2026-11-14"]["calendar_busy_minutes"] == 60


def test_a_week_with_no_calendar_connected_answers_without_one(client):
    # Nothing configured is the state a fresh install is in, and it is not an error: the plan's
    # own figures are complete without the calendar.
    day = week(client)[MONDAY]
    assert day["calendar_busy_minutes"] == 0 and day["open_minutes"] == 1440


def test_an_event_shorter_than_a_minute_still_covers_the_minute_it_is_in():
    # Rounding rather than truncation, so a stored :30 second boundary does not vanish.
    assert day_stats(
        MONDAY,
        [],
        [{"all_day": 0, "start_utc": "2026-09-21T09:00:30+00:00", "end_utc": "2026-09-21T09:00:59+00:00"}],
        timezone.utc,
    )["calendar_busy_minutes"] == 1


def test_the_week_never_reports_more_open_time_than_a_day_holds(client):
    # An all-but-one-hour day: the calendar takes 00:00–23:00, the plan takes the last hour.
    add_calendar()
    add_event(at(0), at(23))
    schedule(client, start_min=1380, duration_min=60)

    day = week(client)[MONDAY]
    assert day["calendar_busy_minutes"] == 1380
    assert day["planned_minutes"] == 60
    assert day["open_minutes"] == 0


def test_the_days_are_the_days_asked_for_in_order(client):
    span = client.get("/api/week?start=2099-01-01&days=3").json()["days"]
    assert [d["day"] for d in span] == ["2099-01-01", "2099-01-02", "2099-01-03"]
