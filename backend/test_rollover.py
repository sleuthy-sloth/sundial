"""Unfinished work from the day before: what qualifies, what moving it costs, and the setting.

Four promises are on trial here, and three of them are about what must *not* happen.

What qualifies is narrow on purpose: an unfinished scheduled block of the immediately previous day,
and nothing else. A calendar event is in another table. A routine's day is not a row at all. A
finished block is finished. Each of those has its own test below, and each is the shape of a bug
that would look like a feature.

The fourth is that reading the day never writes anything. `/api/day` answers with what is left from
yesterday and touches nothing, which is why every test that reads also asks the database what it
looks like afterwards.

The setting is here too rather than in a file of its own: it is what decides whether any of this is
offered, moved, or ignored, and the whole point of it is that it lives in the database the export
carries — so the round trip is part of the same story.

Run with:  cd backend && .venv/bin/pytest -q
"""

import json
from datetime import date as _date
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app
import bootstrap
import export
import store
from clock import today
from services import rollover

# The three days these tests are about. Read from the clock rather than fixed, because the rule
# under test is "the day immediately before today" and a fixed date would test a different rule.
TODAY = today()
YESTERDAY = rollover.day_before(TODAY)
BEFORE_THAT = rollover.day_before(YESTERDAY)
TOMORROW = (_date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()


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
    kw.setdefault("title", "Laundry")
    kw.setdefault("duration_min", 45)
    res = client.post("/api/blocks", json=kw)
    assert res.status_code == 201, res.text
    return res.json()


def left_over(client, day=TODAY) -> list[dict]:
    """What the day view offers as yesterday's unfinished work."""
    answer = client.get(f"/api/day?day={day}")
    assert answer.status_code == 200, answer.text
    return answer.json()["leftover"]


def rows(table: str) -> list[dict]:
    with store.db() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def an_event_on(day: str) -> None:
    """A calendar and one event on it, written the way the sync writes them."""
    with store.db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO calendars (ref, provider, name) VALUES ('c1', 'icloud', 'Home')"
        )
        conn.execute(
            """INSERT INTO events (id, calendar_ref, provider, uid, title, start_utc, end_utc,
                                   all_day, updated_at)
               VALUES ('e1', 'c1', 'icloud', 'u1', 'Dentist', ?, ?, 0, ?)""",
            (f"{day}T16:00:00+00:00", f"{day}T16:30:00+00:00", f"{day}T00:00:00+00:00"),
        )


# ---- what is left from yesterday -----------------------------------------------------------


def test_yesterday_with_unfinished_work_is_offered_on_today(client):
    made(client, title="Call dentist", day=YESTERDAY, start_min=9 * 60, duration_min=20)
    made(client, title="Laundry", day=YESTERDAY, start_min=10 * 60, duration_min=45)

    offered = left_over(client)
    assert [b["title"] for b in offered] == ["Call dentist", "Laundry"], "in the order it was"
    assert [(b["start_min"], b["duration_min"]) for b in offered] == [(540, 20), (600, 45)]
    assert all(b["source"] == "block" and b["done"] is False for b in offered)
    assert all(b["day"] == YESTERDAY for b in offered)


def test_a_yesterday_that_is_finished_is_offered_as_nothing(client):
    first = made(client, title="Laundry", day=YESTERDAY, start_min=600)
    second = made(client, title="Call dentist", day=YESTERDAY, start_min=540, duration_min=20)
    for block in (first, second):
        assert client.patch(f"/api/blocks/{block['id']}", json={"done": True}).status_code == 200

    assert left_over(client) == [], "a finished day has nothing left on it"


def test_only_the_unfinished_half_of_a_mixed_day_is_offered(client):
    done = made(client, title="Laundry", day=YESTERDAY, start_min=600)
    assert client.patch(f"/api/blocks/{done['id']}", json={"done": True}).status_code == 200
    made(client, title="Call dentist", day=YESTERDAY, start_min=540, duration_min=20)

    assert [b["title"] for b in left_over(client)] == ["Call dentist"]


def test_a_block_that_was_never_scheduled_is_not_yesterday_s(client):
    # `day IS NULL` is the inbox, and an inbox item has no day of its own to have been left on.
    # This is the clause that makes moving things to Anytime safe to offer twice.
    made(client, title="Something unscheduled")
    assert left_over(client) == []


def test_a_calendar_event_is_never_left_from_yesterday(client):
    an_event_on(YESTERDAY)
    assert left_over(client) == [], "an event is context, not plan"
    assert len(rows("events")) == 1, "and reading the day did not touch it"


def test_only_the_day_immediately_before_counts(client):
    made(client, title="Older still", day=BEFORE_THAT, start_min=600)
    made(client, title="Yesterday", day=YESTERDAY, start_min=600)
    made(client, title="Today", day=TODAY, start_min=600)

    assert [b["title"] for b in left_over(client)] == ["Yesterday"]


def test_the_section_belongs_to_today_and_not_to_every_day(client):
    # A block on today as well as one on yesterday, or this test could not tell the difference: the
    # question is whether the section is about the day you are in, and with only yesterday's work
    # seeded, a page that offered "the day before this page" would still come out empty.
    made(client, title="Laundry", day=YESTERDAY, start_min=600)
    made(client, title="Today's own", day=TODAY, start_min=600)

    assert [b["title"] for b in left_over(client, YESTERDAY)] == [], (
        "yesterday's page shows those blocks already, and today's work is not yesterday's"
    )
    assert left_over(client, TOMORROW) == [], "and tomorrow is not told about today"
    assert [b["title"] for b in left_over(client, TODAY)] == ["Laundry"]


def test_reading_the_day_writes_nothing(client):
    made(client, title="Laundry", day=YESTERDAY, start_min=600)
    before = rows("blocks")

    left_over(client)
    left_over(client, YESTERDAY)

    assert rows("blocks") == before, "a read moved something"


# ---- the two moves ---------------------------------------------------------------------------


def test_moving_one_item_to_today_keeps_its_time(client):
    block = made(client, title="Laundry", day=YESTERDAY, start_min=600, duration_min=45)

    moved = client.patch(f"/api/blocks/{block['id']}", json={"day": TODAY, "start_min": 600})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["day"], moved.json()["start_min"]) == (TODAY, 600)

    on_today = client.get(f"/api/day?day={TODAY}").json()["blocks"]
    assert [b["id"] for b in on_today] == [block["id"]]
    assert client.get(f"/api/day?day={YESTERDAY}").json()["blocks"] == []
    assert left_over(client) == [], "and it is not offered again"


def test_a_move_is_a_move_and_not_a_copy(client):
    # The honest consequence of reusing the re-day path: the block leaves the day it was on. It is
    # stated in the UI copy and in the release notes, and it is asserted here so that nobody has to
    # take it on trust.
    block = made(client, title="Laundry", day=YESTERDAY, start_min=600)
    client.patch(f"/api/blocks/{block['id']}", json={"day": TODAY, "start_min": 600})

    assert [b["title"] for b in client.get(f"/api/day?day={YESTERDAY}").json()["blocks"]] == []
    assert len(rows("blocks")) == 1, "one row, moved — not a second one"


def test_moving_one_item_to_anytime_puts_it_in_the_inbox(client):
    block = made(client, title="Laundry", day=YESTERDAY, start_min=600, duration_min=45)

    moved = client.patch(f"/api/blocks/{block['id']}", json={"unschedule": True})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["day"], moved.json()["start_min"]) == (None, None)

    day = client.get(f"/api/day?day={TODAY}").json()
    assert day["blocks"] == [], "Anytime is not today"
    assert [b["id"] for b in day["inbox"]] == [block["id"]]
    assert left_over(client) == [], "and an inbox item is never offered again"


def test_a_second_look_offers_nothing_twice(client):
    """The no-duplicates rule, from the only two directions it can be broken from.

    Moving the block is what stops it qualifying — no marker is written to remember it was moved,
    and this is the test that would catch anyone adding one, because the row it would be added to
    is compared whole below.
    """
    block = made(client, title="Laundry", day=YESTERDAY, start_min=600)
    client.patch(f"/api/blocks/{block['id']}", json={"day": TODAY, "start_min": 600})

    assert left_over(client) == []
    assert left_over(client) == []
    assert len(rows("blocks")) == 1
    assert set(rows("blocks")[0]) == {
        "id", "title", "day", "start_min", "duration_min", "color", "icon", "notes", "done",
        "updated_at", "external_uid",
        # The two the checklist migration added, and neither is a marker: `parent_id` says
        # what a row belongs to and `sort_order` says where it sits in a list. A rollover
        # still writes nothing about itself.
        "parent_id", "sort_order",
    }, "a column was added to carry a rollover marker"


def test_a_move_that_lands_back_on_yesterday_is_offered_again(client):
    # Nothing here is a state machine: the rule reads the row. Put it back and it qualifies again,
    # which is what "leave there" relying on nothing but the row's own day means.
    block = made(client, title="Laundry", day=YESTERDAY, start_min=600)
    client.patch(f"/api/blocks/{block['id']}", json={"day": TODAY, "start_min": 600})
    client.patch(f"/api/blocks/{block['id']}", json={"day": YESTERDAY, "start_min": 600})

    assert [b["id"] for b in left_over(client)] == [block["id"]]


# ---- routines: the case the plan warns about -------------------------------------------------


def a_daily_routine(client, title="Gym", start_min=6 * 60 + 30) -> dict:
    """A routine that has been landing every day for a week, so it covers yesterday and today."""
    started = (_date.fromisoformat(TODAY) - timedelta(days=7)).isoformat()
    res = client.post(
        "/api/routines",
        json={"title": title, "start_min": start_min, "duration_min": 60,
              "recurrence_kind": "daily", "start_date": started},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_a_routine_occurrence_is_never_rolled_over(client):
    """The duplicate future routine instance, refused by construction rather than by a filter.

    An occurrence is not a row: yesterday's is drawn from the rule when yesterday is asked for, and
    today's is drawn the same way. Moving yesterday's forward would be the second 06:30 on today.
    """
    routine = a_daily_routine(client)

    yesterday = client.get(f"/api/day?day={YESTERDAY}").json()["blocks"]
    assert [b["source"] for b in yesterday] == ["routine"], "the occurrence was there to be moved"

    assert left_over(client) == [], "a routine's day is not yesterday's unfinished work"
    assert rows("routine_overrides") == [], "and nothing was written about it"

    today_blocks = client.get(f"/api/day?day={TODAY}").json()["blocks"]
    assert [b["id"] for b in today_blocks] == [f"routine:{routine['id']}:{TODAY}"]


def test_a_routine_and_a_block_left_behind_do_not_collide(client):
    """The one case where a rollover and a routine both want the same hour."""
    routine = a_daily_routine(client, start_min=6 * 60 + 30)
    block = made(client, title="Call dentist", day=YESTERDAY, start_min=9 * 60, duration_min=20)

    client.patch(f"/api/blocks/{block['id']}", json={"day": TODAY, "start_min": 9 * 60})

    filled = client.get(f"/api/day?day={TODAY}").json()["blocks"]
    assert [b["id"] for b in filled] == [f"routine:{routine['id']}:{TODAY}", block["id"]]
    assert len({b["start_min"] for b in filled}) == 2, "one occurrence and one block, not two of each"

    # And the rule is untouched: a routine with a day moved onto it never gains an override.
    assert rows("routine_overrides") == []
    assert client.get("/api/routines").json()["routines"][0]["start_min"] == 6 * 60 + 30


def test_a_skipped_routine_day_is_not_offered_and_is_not_put_back(client):
    routine = a_daily_routine(client)
    assert client.post(f"/api/routines/{routine['id']}/occurrences/{YESTERDAY}/skip").status_code == 200

    assert left_over(client) == []
    overrides = rows("routine_overrides")
    assert [(r["routine_id"], r["day"], r["state"]) for r in overrides] == [
        (routine["id"], YESTERDAY, "skipped")
    ], "the skipped day is still the only row about it"


# ---- the setting ------------------------------------------------------------------------------


def test_the_setting_starts_at_ask(client):
    assert client.get("/api/settings").json() == {"rollover": "ask"}
    assert rows("settings") == [], "a default is not a row"


def test_the_setting_is_stored_in_the_database(client):
    answer = client.patch("/api/settings", json={"rollover": "anytime"})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"rollover": "anytime"}
    assert client.get("/api/settings").json() == {"rollover": "anytime"}

    stored = rows("settings")
    assert [(r["key"], r["value"]) for r in stored] == [("rollover", "anytime")]
    assert stored[0]["updated_at"], "a stored setting says when it was chosen"

    # Choosing again replaces rather than accumulating.
    client.patch("/api/settings", json={"rollover": "leave"})
    assert [(r["key"], r["value"]) for r in rows("settings")] == [("rollover", "leave")]


def test_every_value_the_panel_offers_is_one_the_api_takes(client):
    from services.settings import ROLLOVER

    for value in ROLLOVER:
        assert client.patch("/api/settings", json={"rollover": value}).status_code == 200, value
    assert client.get("/api/settings").json()["rollover"] == ROLLOVER[-1]


def test_a_value_that_is_not_one_of_the_three_is_refused_with_the_choices(client):
    answer = client.patch("/api/settings", json={"rollover": "ask me later"})
    assert answer.status_code == 400, answer.text
    detail = answer.json()["detail"]
    assert "ask" in detail and "anytime" in detail and "leave" in detail, detail
    assert client.get("/api/settings").json() == {"rollover": "ask"}, "nothing was written"


def test_a_null_or_unknown_setting_is_refused_rather_than_dropped(client):
    assert client.patch("/api/settings", json={"rollover": None}).status_code == 400
    # An unknown name is a 422 from the body rather than a silent success: a build that knows a
    # setting this one does not must not be told its choice was saved.
    assert client.patch("/api/settings", json={"rolloverr": "anytime"}).status_code == 422
    assert client.get("/api/settings").json() == {"rollover": "ask"}


def test_a_patch_that_names_nothing_changes_nothing(client):
    assert client.patch("/api/settings", json={}).json() == {"rollover": "ask"}


def test_a_stored_value_the_api_would_refuse_is_answered_with_the_default(client):
    with store.db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('rollover', 'later', 'x')"
        )
    assert client.get("/api/settings").json() == {"rollover": "ask"}


# ---- leaving: the setting in the file --------------------------------------------------------


def test_the_setting_survives_an_export_and_an_import(client):
    client.patch("/api/settings", json={"rollover": "anytime"})
    document = json.loads(json.dumps(client.get("/api/export").json()))
    assert [r["value"] for r in document["tables"]["settings"]] == ["anytime"]

    where = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert where.status_code == 200, where.text
    assert client.get("/api/settings").json() == {"rollover": "anytime"}


def test_a_file_from_before_settings_still_imports_and_empties_them(client):
    """A version 2 file promised no settings table, so it is a whole file without one."""
    client.patch("/api/settings", json={"rollover": "leave"})
    document = json.loads(json.dumps(client.get("/api/export").json()))
    document["version"] = 2
    del document["tables"]["settings"]

    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["replaced"]["settings"] == 0, "the setting it never carried was not left"
    assert client.get("/api/settings").json() == {"rollover": "ask"}


def test_a_current_file_missing_the_settings_table_is_refused(client):
    document = json.loads(json.dumps(client.get("/api/export").json()))
    del document["tables"]["settings"]

    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 400, answer.text
    assert "settings" in answer.json()["detail"]


def test_the_settings_table_is_what_a_fresh_database_gets(client):
    with store.db() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
        versions = [r["version"] for r in conn.execute("SELECT version FROM schema_version")]
    assert {"key", "value", "updated_at"} <= columns
    # 6 is the migration that made this table, so it has to have run — and everything on disk
    # above it too, which is the part that does not need editing every time a table is added.
    assert 6 in versions, "the migration that makes the settings table did not run"
    newest = max(int(p.name.split("_", 1)[0]) for p in bootstrap.MIGRATIONS.glob("*.sql"))
    assert max(versions) == newest, "a migration on disk was not applied"
    assert "settings" in export.TABLES
