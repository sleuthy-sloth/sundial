"""Repeating routines: the rule, the days it lands on, and the days you changed.

Two promises are on trial here. The first is that nothing is generated — the whole design exists
so a daily routine does not leave a year of rows behind it, and the way to test a promise like
that is to ask for the year and count what was written. The second is that one day can differ
from its rule without the rule moving, which is what makes a routine safe to have at all.

The recurrence rule itself is tested through `occurs_on` as well as over HTTP, because it is a
pure function of a rule and a date and there is no reason to start a server to ask it a question.

Run with:  cd backend && .venv/bin/pytest -q
"""

import json

import pytest
from fastapi.testclient import TestClient

import app
import export
import store
from services import routines

# A Monday, and the days around it. Every weekday assertion below reads off these.
MON = "2027-03-08"
TUE = "2027-03-09"
WED = "2027-03-10"
FRI = "2027-03-12"
SAT = "2027-03-13"
SUN = "2027-03-14"

# The two days a year that are not 24 hours long in most of the world. US daylight saving moved
# forward on the first of these and back on the second, so a rule that counted in local time
# would drift by an hour on them and a rule that counts in days cannot.
SPRING_FORWARD = {"first": "2027-03-12", "last": "2027-03-16", "days": 5}
FALL_BACK = {"first": "2026-10-30", "last": "2026-11-03", "days": 5}


@pytest.fixture
def database(tmp_path, monkeypatch):
    """A real database — this app's own schema — in a file of this test's own."""
    path = tmp_path / "sundial.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    app.bootstrap()
    return path


@pytest.fixture
def client(database):
    return TestClient(app.app)


def made(client, **kw) -> dict:
    kw.setdefault("title", "Gym")
    kw.setdefault("start_min", 6 * 60 + 30)
    kw.setdefault("duration_min", 60)
    kw.setdefault("recurrence_kind", "daily")
    res = client.post("/api/routines", json=kw)
    assert res.status_code == 201, res.text
    return res.json()


def on_day(client, day):
    """The day, as the API reports it."""
    res = client.get("/api/day", params={"day": day})
    assert res.status_code == 200, res.text
    return res.json()["blocks"]


def occurrence(client, routine_id, day):
    """The occurrence of one routine on one day, or None if there is not one."""
    for block in on_day(client, day):
        if block.get("routine_id") == routine_id:
            return block
    return None


def rule(**kw) -> dict:
    """A routine mapping as `occurs_on` reads one — the shape the API hands out."""
    base = {
        "id": "r1", "title": "Gym", "start_min": 390, "duration_min": 60, "color": "slate",
        "icon": "", "notes": "", "recurrence_kind": "daily", "weekdays": [], "interval_weeks": 1,
        "start_date": MON, "end_date": None, "enabled": True, "updated_at": "2027-03-01T00:00:00",
    }
    base.update(kw)
    return base


def days_between(routine_map, first, last):
    """Every day this rule lands on inside a range, by asking day by day."""
    from datetime import date as _date
    from datetime import timedelta

    out = []
    day = _date.fromisoformat(first)
    end = _date.fromisoformat(last)
    while day <= end:
        if routines.occurs_on(routine_map, day.isoformat()):
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def rows(table):
    with store.db() as conn:
        return list(conn.execute(f"SELECT * FROM {table}"))


# ---- the rule, asked directly --------------------------------------------------------------


def test_daily_is_every_day_inside_its_dates():
    r = rule(recurrence_kind="daily", start_date="2027-03-08", end_date="2027-03-11")
    assert days_between(r, "2027-03-01", "2027-03-20") == [
        "2027-03-08", "2027-03-09", "2027-03-10", "2027-03-11",
    ]


def test_weekdays_skips_the_weekend():
    r = rule(recurrence_kind="weekdays")
    assert days_between(r, MON, SUN) == [MON, TUE, "2027-03-10", "2027-03-11", FRI]


def test_weekends_is_saturday_and_sunday_only():
    r = rule(recurrence_kind="weekends")
    assert days_between(r, MON, SUN) == [SAT, SUN]


def test_selected_weekdays_is_the_set_it_was_given():
    r = rule(recurrence_kind="selected_weekdays", weekdays=[1, 3, 5])
    assert days_between(r, MON, SUN) == [MON, "2027-03-10", FRI]


def test_a_weekly_interval_counts_from_the_day_it_starts():
    # Anchored on a Monday, every second week: the same weekday, fourteen days apart.
    r = rule(recurrence_kind="weekly_interval", interval_weeks=2, start_date=MON)
    assert days_between(r, MON, "2027-04-05") == [MON, "2027-03-22", "2027-04-05"]


def test_every_week_is_the_same_weekday_every_seven_days():
    r = rule(recurrence_kind="weekly_interval", interval_weeks=1, start_date=MON)
    assert days_between(r, MON, "2027-03-29") == [MON, "2027-03-15", "2027-03-22", "2027-03-29"]


def test_the_start_date_is_a_floor_not_a_suggestion():
    r = rule(recurrence_kind="daily", start_date="2027-03-10")
    assert days_between(r, "2027-03-01", "2027-03-12") == ["2027-03-10", "2027-03-11",
                                                           "2027-03-12"]


def test_the_end_date_is_inclusive_and_can_be_the_only_day():
    r = rule(recurrence_kind="daily", start_date="2027-03-10", end_date="2027-03-10")
    assert days_between(r, "2027-03-01", "2027-03-20") == ["2027-03-10"]


def test_a_routine_that_is_off_happens_nowhere():
    r = rule(recurrence_kind="daily", enabled=False)
    assert days_between(r, MON, SUN) == []


@pytest.mark.parametrize("boundary", [SPRING_FORWARD, FALL_BACK])
def test_a_daily_routine_across_a_clock_change_still_lands_on_every_day(boundary):
    """The day it is, not the hours it has.

    An occurrence is a calendar day and a minute past midnight on that day, so a date that lost
    or gained an hour is not a special case — and this is the check that says so rather than
    assuming it. Counting in local time, or storing an instant, is how a 365-day year becomes
    364 or 366.
    """
    r = rule(recurrence_kind="daily", start_date=boundary["first"])
    landed = days_between(r, boundary["first"], boundary["last"])
    assert len(landed) == boundary["days"]
    assert landed[0] == boundary["first"] and landed[-1] == boundary["last"]
    assert len(set(landed)) == len(landed), "a day was counted twice"


def test_a_weekly_routine_keeps_its_weekday_across_a_clock_change():
    # Every Monday and Wednesday, over the week the clocks went forward: the rule is a weekday,
    # and a weekday is not something an hour can move.
    r = rule(
        recurrence_kind="selected_weekdays", weekdays=[1, 3], start_date="2027-03-08"
    )
    assert days_between(r, "2027-03-08", "2027-03-21") == [
        "2027-03-08", "2027-03-10", "2027-03-15", "2027-03-17",
    ]


def test_an_unknown_rule_happens_nowhere_rather_than_somewhere():
    assert days_between(rule(recurrence_kind="fortnightly"), MON, SUN) == []


# ---- over HTTP: the day view ---------------------------------------------------------------


def test_a_daily_routine_appears_on_every_day_and_never_before_it_starts(client):
    gym = made(client, start_date="2027-03-10", start_min=390, duration_min=60)

    assert on_day(client, "2027-03-09") == []
    got = occurrence(client, gym["id"], "2027-03-10")
    assert (got["title"], got["start_min"], got["duration_min"]) == ("Gym", 390, 60)


def test_an_occurrence_says_where_it_came_from(client):
    gym = made(client, start_date=MON)
    got = occurrence(client, gym["id"], MON)

    assert got["source"] == "routine"
    assert got["routine_id"] == gym["id"]
    assert got["occurrence_day"] == MON
    assert got["day"] == MON
    # An id that no block route will ever find, so an occurrence can never be written as a row
    # that was never created.
    assert got["id"] == f"routine:{gym['id']}:{MON}"
    assert client.patch(f"/api/blocks/{got['id']}", json={"title": "nope"}).status_code == 404
    assert client.delete(f"/api/blocks/{got['id']}").status_code == 404


def test_the_day_is_one_list_in_the_order_it_happens(client):
    made(client, title="Gym", start_date=MON, start_min=390)
    made(client, title="Medication", start_date=MON, start_min=420, duration_min=5)
    client.post("/api/blocks", json={"title": "Standup", "day": MON, "start_min": 405,
                                     "duration_min": 15})

    assert [(b["title"], b["start_min"]) for b in on_day(client, MON)] == [
        ("Gym", 390), ("Standup", 405), ("Medication", 420),
    ]


def test_asking_for_a_year_creates_nothing(client):
    """The reason the occurrences are virtual, tested in the only way that means anything.

    A daily routine asked about 400 days ahead is still one row in `routines` and no rows at all
    anywhere else. If this ever fails, the feature has become a table of copies.
    """
    gym = made(client, start_date=MON)

    from datetime import date as _date
    from datetime import timedelta

    day = _date.fromisoformat(MON)
    for _ in range(400):
        client.get("/api/day", params={"day": day.isoformat()})
        day += timedelta(days=1)

    assert len(rows("routines")) == 1
    assert rows("routine_overrides") == []
    assert occurrence(client, gym["id"], "2028-04-11") is not None


def test_the_week_counts_routines_as_time_spoken_for(client):
    made(client, title="Gym", start_date=MON, start_min=390, duration_min=60)
    client.post("/api/blocks", json={"title": "Standup", "day": MON, "start_min": 540,
                                     "duration_min": 30})

    week = client.get("/api/week", params={"start": MON, "days": 7}).json()["days"]
    load = {d["day"]: (d["blocks"], d["minutes"]) for d in week}
    assert load[MON] == (2, 90)
    assert load[TUE] == (1, 60)  # the routine is on Tuesday too; the block is not
    assert load[SUN] == (1, 60)


# ---- one day at a time ---------------------------------------------------------------------


def test_changing_one_occurrence_leaves_the_rule_and_every_other_day_alone(client):
    gym = made(client, title="Gym", start_date=MON, start_min=390, duration_min=60)

    res = client.patch(
        f"/api/routines/{gym['id']}/occurrences/{MON}",
        json={"start_min": 6 * 60, "duration_min": 45, "notes": "the 6am class"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["occurrence"]["start_min"] == 360

    moved = occurrence(client, gym["id"], MON)
    assert (moved["start_min"], moved["duration_min"], moved["notes"]) == (360, 45,
                                                                          "the 6am class")
    # The next day is untouched: same time as the rule, no notes, not done.
    other = occurrence(client, gym["id"], TUE)
    assert (other["start_min"], other["duration_min"], other["notes"], other["done"]) == (
        390, 60, "", False,
    )
    # And the rule itself never moved.
    assert client.get("/api/routines").json()["routines"][0]["start_min"] == 390


def test_skipping_one_day_removes_that_day_only(client):
    gym = made(client, start_date=MON)

    res = client.post(f"/api/routines/{gym['id']}/occurrences/{MON}/skip")
    assert res.status_code == 200, res.text
    assert res.json()["occurrence"] is None, "a skipped day is not on the day"

    assert occurrence(client, gym["id"], MON) is None
    assert occurrence(client, gym["id"], TUE) is not None
    assert rows("routine_overrides")[0]["state"] == "skipped"
    # The rule still says every day: skipping a day is not editing the routine.
    assert client.get("/api/routines").json()["routines"][0]["recurrence_kind"] == "daily"


def test_finishing_one_occurrence_finishes_only_that_day(client):
    gym = made(client, start_date=MON)

    res = client.patch(
        f"/api/routines/{gym['id']}/occurrences/{MON}", json={"done": True}
    )
    assert res.json()["occurrence"]["done"] is True

    assert occurrence(client, gym["id"], MON)["done"] is True
    assert occurrence(client, gym["id"], TUE)["done"] is False
    assert rows("routine_overrides")[0]["state"] == "completed"


def test_a_day_put_back_to_the_rule_leaves_no_row_behind(client):
    gym = made(client, start_date=MON)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"done": True})
    assert len(rows("routine_overrides")) == 1

    res = client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"done": False})
    assert res.status_code == 200
    assert res.json()["occurrence"]["done"] is False
    assert rows("routine_overrides") == [], "an override that says nothing was kept"


def test_editing_a_skipped_day_puts_it_back(client):
    gym = made(client, start_date=MON)
    client.post(f"/api/routines/{gym['id']}/occurrences/{MON}/skip")
    assert occurrence(client, gym["id"], MON) is None

    res = client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"start_min": 420})
    assert res.json()["occurrence"]["start_min"] == 420
    assert occurrence(client, gym["id"], MON) is not None


def test_skipping_a_day_you_had_already_changed_keeps_the_change(client):
    gym = made(client, start_date=MON)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"title": "Swim"})
    client.post(f"/api/routines/{gym['id']}/occurrences/{MON}/skip")
    assert occurrence(client, gym["id"], MON) is None

    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"skipped": False})
    assert occurrence(client, gym["id"], MON)["title"] == "Swim"


def test_resetting_a_day_undoes_the_change_for_good(client):
    gym = made(client, start_date=MON)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}",
                 json={"start_min": 360, "title": "Swim"})

    res = client.delete(f"/api/routines/{gym['id']}/occurrences/{MON}")
    assert res.status_code == 200, res.text
    got = res.json()["occurrence"]
    assert (got["title"], got["start_min"]) == ("Gym", 390)
    assert rows("routine_overrides") == []
    # Nothing was ever changed: there is nothing to reset, and saying so beats a silent 200.
    assert client.delete(f"/api/routines/{gym['id']}/occurrences/{MON}").status_code == 404


def test_editing_the_routine_changes_every_day_it_has_not_been_told_otherwise(client):
    """The other half of the pair: "from now on" and "just this once" have to differ."""
    gym = made(client, title="Gym", start_date=MON, start_min=390)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"title": "Swim"})

    res = client.patch(f"/api/routines/{gym['id']}", json={"title": "Gym session",
                                                          "start_min": 7 * 60})
    assert res.status_code == 200, res.text

    # The day with its own title keeps it, and takes the new time — an override replaces only
    # what it holds.
    changed = occurrence(client, gym["id"], MON)
    assert (changed["title"], changed["start_min"]) == ("Swim", 420)
    # Every untouched day takes both.
    later = occurrence(client, gym["id"], "2027-03-15")
    assert (later["title"], later["start_min"]) == ("Gym session", 420)


def test_turning_a_routine_off_takes_it_off_every_day_without_losing_the_days(client):
    gym = made(client, start_date=MON)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"start_min": 360})

    client.patch(f"/api/routines/{gym['id']}", json={"enabled": False})
    assert on_day(client, MON) == []
    assert rows("routine_overrides")[0]["start_min"] == 360, "the day was thrown away with it"

    client.patch(f"/api/routines/{gym['id']}", json={"enabled": True})
    assert occurrence(client, gym["id"], MON)["start_min"] == 360


def test_deleting_a_routine_takes_its_days_with_it(client):
    gym = made(client, start_date=MON)
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"title": "Swim"})

    assert client.delete(f"/api/routines/{gym['id']}").status_code == 204
    assert rows("routines") == []
    assert rows("routine_overrides") == [], "an override outlived its routine"
    assert on_day(client, MON) == []
    assert client.delete(f"/api/routines/{gym['id']}").status_code == 404


# ---- what a routine refuses ----------------------------------------------------------------


def test_a_custom_repeat_with_no_days_is_refused(client):
    res = client.post("/api/routines", json={
        "title": "Gym", "start_min": 390, "recurrence_kind": "selected_weekdays",
    })
    assert res.status_code == 400, res.text
    assert "at least one day" in res.json()["detail"]
    assert rows("routines") == []


def test_an_unknown_repeat_is_refused_with_the_list(client):
    res = client.post("/api/routines", json={
        "title": "Gym", "start_min": 390, "recurrence_kind": "fortnightly",
    })
    assert res.status_code == 400, res.text
    assert "fortnightly" in res.json()["detail"]
    assert "weekly_interval" in res.json()["detail"]


def test_a_routine_cannot_end_before_it_starts(client):
    res = client.post("/api/routines", json={
        "title": "Gym", "start_min": 390, "recurrence_kind": "daily",
        "start_date": MON, "end_date": "2027-03-01",
    })
    assert res.status_code == 400, res.text
    assert "before it starts" in res.json()["detail"]

    gym = made(client, start_date=MON)
    assert client.patch(f"/api/routines/{gym['id']}", json={"end_date": "2027-03-01"}).status_code \
        == 400


def test_a_weekday_outside_the_week_is_refused(client):
    res = client.post("/api/routines", json={
        "title": "Gym", "start_min": 390, "recurrence_kind": "selected_weekdays",
        "weekdays": [1, 9],
    })
    assert res.status_code == 400, res.text
    assert "1 (Monday) to 7 (Sunday)" in res.json()["detail"]


def test_a_routine_that_runs_past_midnight_is_refused(client):
    res = client.post("/api/routines", json={
        "title": "Night shift", "start_min": 1430, "duration_min": 60,
        "recurrence_kind": "daily",
    })
    assert res.status_code == 400, res.text
    assert "past midnight" in res.json()["detail"]


def test_a_day_that_is_changed_to_run_past_midnight_is_refused(client):
    gym = made(client, start_date=MON, start_min=1400, duration_min=30)
    res = client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"duration_min": 120})
    assert res.status_code == 400, res.text
    assert rows("routine_overrides") == [], "a refused change was written anyway"


def test_an_unknown_colour_is_refused(client):
    res = client.post("/api/routines", json={
        "title": "Gym", "start_min": 390, "recurrence_kind": "daily", "color": "chartreuse",
    })
    assert res.status_code == 400, res.text
    assert "chartreuse" in res.json()["detail"]


def test_the_routes_refuse_a_day_the_rule_does_not_reach(client):
    """A 400 rather than a 404: the routine is there, the day is not one of its days."""
    gym = made(client, start_date=MON, recurrence_kind="weekdays")

    for method, path in (
        ("post", f"/api/routines/{gym['id']}/occurrences/{SAT}/skip"),
        ("patch", f"/api/routines/{gym['id']}/occurrences/{SAT}"),
        ("delete", f"/api/routines/{gym['id']}/occurrences/{SAT}"),
    ):
        res = client.request(
            method.upper(), path, json={"title": "x"} if method == "patch" else None
        )
        assert res.status_code == 400, f"{method} {path}: {res.text}"
        assert "has no occurrence on" in res.json()["detail"]

    assert client.post(
        f"/api/routines/{gym['id']}/occurrences/2027-3-13/skip"
    ).status_code == 400, "a day that is not a day is still refused"
    assert rows("routine_overrides") == []


def test_an_unknown_routine_is_a_404_everywhere(client):
    assert client.get("/api/routines").json() == {"routines": []}
    assert client.patch("/api/routines/nope", json={"title": "x"}).status_code == 404
    assert client.delete("/api/routines/nope").status_code == 404
    assert client.post("/api/routines/nope/occurrences/2027-03-08/skip").status_code == 404


def test_a_null_on_a_column_that_cannot_hold_one_is_a_4xx(client):
    gym = made(client, start_date=MON)
    for path, field in (
        (f"/api/routines/{gym['id']}", "title"),
        (f"/api/routines/{gym['id']}", "enabled"),
        (f"/api/routines/{gym['id']}/occurrences/{MON}", "title"),
    ):
        res = client.patch(path, json={field: None})
        assert res.status_code == 400, res.text
        assert isinstance(res.json()["detail"], str), "the client needs a sentence it can print"

    # The one field that may be nulled is the one whose null means something.
    assert client.patch(f"/api/routines/{gym['id']}", json={"end_date": None}).status_code == 200


def test_a_blank_title_is_refused_on_a_routine_and_on_a_day(client):
    assert client.post("/api/routines", json={
        "title": "  ", "start_min": 390, "recurrence_kind": "daily",
    }).status_code == 400

    gym = made(client, start_date=MON)
    assert client.patch(f"/api/routines/{gym['id']}", json={"title": "   "}).status_code == 400
    res = client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}", json={"title": "  "})
    assert res.status_code == 400, res.text
    assert occurrence(client, gym["id"], MON)["title"] == "Gym"


def test_a_routine_is_reported_the_way_it_was_asked_for(client):
    gym = made(client, start_date=MON, recurrence_kind="selected_weekdays", weekdays=[5, 1, 3, 1],
               interval_weeks=2, notes="bring the mat")

    assert gym["weekdays"] == [1, 3, 5], "the days come back sorted and deduplicated"
    assert gym["enabled"] is True
    assert gym["summary"] == "Mon · Wed · Fri"
    assert gym["interval_weeks"] == 2
    assert gym["notes"] == "bring the mat"
    assert gym["id"] in [r["id"] for r in client.get("/api/routines").json()["routines"]]


def test_a_new_routine_takes_the_next_colour_when_none_is_given(client):
    first = made(client, title="Gym", start_date=MON)
    second = made(client, title="Medication", start_date=MON)
    assert first["color"] != second["color"]
    assert client.post("/api/routines", json={
        "title": "Chosen", "start_min": 390, "recurrence_kind": "daily", "color": "teal",
    }).json()["color"] == "teal"


def test_the_states_sqlite_keeps_are_the_states_this_code_writes(client):
    """The invariant the migration declares, checked against SQLite rather than trusted.

    `completed` and `done = 1` are one statement in two columns; a row that says one and means
    the other is refused by the table itself, so no reader has to work out which to believe.
    """
    gym = made(client, start_date=MON)
    with store.db() as conn:
        with pytest.raises(Exception):
            conn.execute(
                """INSERT INTO routine_overrides (id, routine_id, day, state, done, updated_at)
                   VALUES ('bad', ?, ?, 'completed', 0, '2027-03-01T00:00:00')""",
                (gym["id"], MON),
            )
    assert rows("routine_overrides") == []


# ---- leaving: export and import ------------------------------------------------------------


def seed_routine(client):
    """A routine with both kinds of opinion on it: one day moved, one day taken out."""
    gym = made(client, title="Gym", start_date=MON, recurrence_kind="selected_weekdays",
               weekdays=[1, 3, 5], start_min=390, duration_min=60, icon="🏋️")
    client.patch(f"/api/routines/{gym['id']}/occurrences/{MON}",
                 json={"start_min": 420, "notes": "later today"})
    assert client.post(f"/api/routines/{gym['id']}/occurrences/{WED}/skip").status_code == 200
    return gym


def test_routines_and_their_days_survive_a_round_trip(client):
    seed_routine(client)
    document = client.get("/api/export").json()
    assert document["version"] == 2, "files that carry routines are a new format version"
    assert len(document["tables"]["routines"]) == 1
    assert len(document["tables"]["routine_overrides"]) == 2
    assert len(document["tables"]["routine_overrides"][0]) == 12
    assert "password" not in json.dumps(document).lower()

    with store.db() as conn:
        for name in export.TABLES:
            conn.execute(f"DELETE FROM {name}")

    answer = client.post("/api/import", json={"confirm": "replace everything",
                                              "document": document})
    assert answer.status_code == 200, answer.text

    gym = client.get("/api/routines").json()["routines"][0]
    assert (gym["title"], gym["weekdays"], gym["icon"]) == ("Gym", [1, 3, 5], "🏋️")
    monday = occurrence(client, gym["id"], MON)
    assert (monday["start_min"], monday["notes"]) == (420, "later today")
    assert occurrence(client, gym["id"], WED) is None, "the skipped day was lost"
    assert occurrence(client, gym["id"], FRI)["start_min"] == 390


def test_an_override_naming_a_routine_the_file_does_not_carry_is_refused(client):
    """Referential integrity, from the side a person can actually produce."""
    seed_routine(client)
    document = client.get("/api/export").json()
    before = {name: len(rows(name)) for name in export.TABLES}

    document["tables"]["routines"] = []

    answer = client.post("/api/import", json={"confirm": "replace everything",
                                              "document": document})
    assert answer.status_code == 400, "an orphaned day should be a refusal, not a 500"
    assert "contradicts itself" in answer.json()["detail"]
    assert {name: len(rows(name)) for name in export.TABLES} == before


def test_a_file_from_before_routines_still_imports_and_still_empties_them(client):
    """The reason the format carries a version at all.

    A file written before this release has no routines table because there were no routines. It
    is complete, so it imports — and what it says about routines is nothing, which has to mean
    the routines are gone rather than that they were left where they were.
    """
    seed_routine(client)
    document = client.get("/api/export").json()

    older = dict(document, version=1)
    older["tables"] = {name: document["tables"][name] for name in export.TABLES_BY_VERSION[1]}
    assert "routines" not in older["tables"]

    answer = client.post("/api/import", json={"confirm": "replace everything", "document": older})
    assert answer.status_code == 200, answer.text
    assert answer.json()["replaced"]["routines"] == 0
    assert rows("routines") == []
    assert rows("routine_overrides") == []
    assert len(rows("blocks")) == len(document["tables"]["blocks"])


def test_a_current_file_missing_the_routines_table_is_still_refused(client):
    seed_routine(client)
    document = client.get("/api/export").json()
    del document["tables"]["routines"]

    answer = client.post("/api/import", json={"confirm": "replace everything", "document": document})
    assert answer.status_code == 400
    assert "missing the routines" in answer.json()["detail"]
    assert len(rows("routines")) == 1
