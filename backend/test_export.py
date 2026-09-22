"""Leaving: the whole database as JSON, and putting it back.

The risk these cover is not corruption, it is a promise. A file offered as "your data,
you can leave whenever" is only worth the two things it claims: that it holds what it
says it holds, and that importing it does what it says. So the round trip is tested
against the real schema rather than a toy one, the refusals are tested as carefully as
the successes, and the destructive path is tested for what it does when it fails.

The one that matters most is the atomicity test. "Replace everything" that half works
is worse than one that refuses, because the half that worked looks like the whole thing.

Run with:  cd backend && .venv/bin/pytest -q
"""

import json
import pathlib
import sqlite3

import pytest

from fastapi.testclient import TestClient

import app
import export
import store

from services import routines

ROOT = pathlib.Path(__file__).resolve().parent


@pytest.fixture
def client(database):
    """The real app over the test's database. No context manager, so the lifespan does
    not start: these tests are about the two endpoints, not about the notification tick."""
    return TestClient(app.app)


@pytest.fixture
def database(tmp_path, monkeypatch):
    """A real database — the app's own schema — in a file of this test's own.

    `store.DB_PATH` is read when a connection is opened rather than at import, so
    pointing it here keeps this module independent of which test file was imported
    first. A second test module cannot drag this one onto its database.
    """
    path = tmp_path / "sundial.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    app.bootstrap()
    return path


def seed():
    """One of everything, with a real shape: a calendar, a block, and its event."""
    with store.db() as conn:
        conn.execute(
            "INSERT INTO calendars (ref, provider, name) VALUES ('home', 'icloud', 'Home')"
        )
        conn.execute(
            """INSERT INTO blocks (id, title, day, start_min, duration_min, updated_at, icon)
               VALUES ('b1', 'Write the thing', '2026-09-21', 540, 90,
                       '2026-09-21T08:00:00+00:00', 'pen')"""
        )
        conn.execute(
            """INSERT INTO blocks (id, title, updated_at)
               VALUES ('b2', 'Something for later', '2026-09-21T09:00:00+00:00')"""
        )
        conn.execute(
            """INSERT INTO events (id, calendar_ref, provider, uid, title, start_utc, end_utc,
                                   updated_at)
               VALUES ('e1', 'home', 'icloud', 'uid-1', 'Dentist',
                       '2026-09-21T17:00:00+00:00', '2026-09-21T18:00:00+00:00',
                       '2026-09-20T00:00:00+00:00')"""
        )
        conn.execute(
            """INSERT INTO sync_log (at, provider, action, detail)
               VALUES ('2026-09-21T07:00:00+00:00', 'icloud', 'pull', '3 events')"""
        )
        conn.execute(
            """INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
               VALUES ('https://push.example/abc', 'key', 'auth', '2026-09-21T07:00:00+00:00')"""
        )


def everything():
    """Every carried table's rows, as comparable tuples."""
    with store.db() as conn:
        return {
            name: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {name}"))
            for name in export.TABLES
        }


def test_a_round_trip_brings_the_data_back_unchanged(database):
    seed()
    before = everything()

    with store.db() as conn:
        document = json.loads(json.dumps(export.dump(conn, 5)))  # through real JSON
        assert export.counts(document) == {
            "calendars": 1, "routines": 0, "routine_overrides": 0, "blocks": 2,
            "events": 1, "sync_log": 1, "push_sent": 0,
        }

    # Empty it, the way a fresh install on another machine would be. Importing the same
    # document back over itself would prove nothing: it would pass whether or not the
    # deletes ever ran.
    emptied = dict(document, tables={name: [] for name in export.TABLES})
    with store.db() as conn:
        export.replace(conn, export.check(emptied, 5))
    assert everything() == {name: [] for name in export.TABLES}, "the import was not a replace"

    # And take them back to where they started.
    with store.db() as conn:
        written = export.replace(conn, export.check(document, 5))
    assert everything() == before, "the round trip lost or changed something"
    assert written == {"calendars": 1, "routines": 0, "routine_overrides": 0, "blocks": 2,
                       "events": 1, "sync_log": 1, "push_sent": 0}


def test_a_routine_and_the_days_it_was_told_otherwise_survive_a_round_trip(database):
    """A rule and its exceptions, out through real JSON and back.

    Both halves have to survive together. A routine without its overrides would quietly put back
    a day you had taken out, and an override without its routine is a row about nothing — so this
    checks the rows *and* the days they answer for, because a file that restores the rows and
    changes what they mean is not a restore.

    A routine is the one thing in the database that is mostly not rows: the days it covers are
    computed from the rule, and the only rows it owns are the days you disagreed with. So the
    question after the round trip is not "are the rows here" but "is Wednesday still skipped".
    """
    seed()
    with store.db() as conn:
        conn.execute(
            """INSERT INTO routines (id, title, start_min, duration_min, color, icon, notes,
                                     recurrence_kind, weekdays, interval_weeks, start_date,
                                     end_date, created_at, updated_at, enabled)
               VALUES ('r1', 'Gym', 390, 60, 'emerald', '', '', 'selected_weekdays', '1,3,5',
                       1, '2026-09-21', NULL, '2026-09-21T06:00:00+00:00',
                       '2026-09-21T06:00:00+00:00', 1)"""
        )
        # One day taken out entirely, and one that only moved: the two shapes an override takes,
        # and the two that have to come back differently.
        conn.execute(
            """INSERT INTO routine_overrides (id, routine_id, day, state, done, updated_at)
               VALUES ('o1', 'r1', '2026-09-23', 'skipped', 0, '2026-09-22T20:00:00+00:00')"""
        )
        conn.execute(
            """INSERT INTO routine_overrides (id, routine_id, day, state, start_min, done,
                                             updated_at)
               VALUES ('o2', 'r1', '2026-09-25', 'modified', 420, 0,
                       '2026-09-25T05:00:00+00:00')"""
        )

    def the_days_answers():
        """What the rule says about its three days, as a person would read them."""
        with store.db() as conn:
            return {
                "monday": [o["title"] for o in routines.occurrences_on(conn, "2026-09-21")],
                "wednesday": routines.occurrences_on(conn, "2026-09-23"),
                "friday": [o["start_min"] for o in routines.occurrences_on(conn, "2026-09-25")],
            }

    before = everything()
    assert the_days_answers() == {"monday": ["Gym"], "wednesday": [], "friday": [420]}

    with store.db() as conn:
        document = json.loads(json.dumps(export.dump(conn, 5)))  # through real JSON
    assert export.counts(document)["routines"] == 1
    assert export.counts(document)["routine_overrides"] == 2

    emptied = dict(document, tables={name: [] for name in export.TABLES})
    with store.db() as conn:
        export.replace(conn, export.check(emptied, 5))

    with store.db() as conn:
        export.replace(conn, export.check(document, 5))

    assert everything() == before, "the round trip lost or changed a routine or one of its days"
    assert the_days_answers() == {"monday": ["Gym"], "wednesday": [], "friday": [420]}, (
        "the rows came back but the days they answer for did not"
    )


def test_a_block_with_no_day_survives_being_carried(database):
    # The inbox is `day IS NULL` and `start_min IS NULL`, which is the one row shape a
    # naive export is most likely to mangle.
    seed()
    with store.db() as conn:
        document = json.loads(json.dumps(export.dump(conn, 4)))
        export.replace(conn, export.check(document, 4))
        inbox = conn.execute("SELECT title, day, start_min FROM blocks WHERE id = 'b2'").fetchone()
    assert inbox["day"] is None and inbox["start_min"] is None


def test_an_export_does_not_carry_a_devices_notification_endpoint(database):
    # An endpoint is a capability: anyone holding it can notify that device. It does not
    # belong in a file people mail to themselves.
    seed()
    with store.db() as conn:
        document = export.dump(conn, 4)
        assert "push_subscriptions" not in document["tables"]
    assert "https://push.example/abc" not in json.dumps(document)
    assert export.NOT_CARRIED["push_subscriptions"], "the reason should travel with the decision"


def test_importing_leaves_the_current_devices_subscription_alone(database):
    # Restoring your data must not silently unsubscribe the phone in your pocket.
    seed()
    with store.db() as conn:
        document = export.dump(conn, 4)
        export.replace(conn, export.check(document, 4))
        left = conn.execute("SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()["n"]
    assert left == 1, "an import unsubscribed the device"


def test_it_refuses_a_file_that_is_not_a_sundial_export(database):
    for rubbish in ({"hello": "world"}, [1, 2, 3], "a string"):
        with pytest.raises(export.ExportError, match="not a sundial export"):
            export.check(rubbish, 4)


def test_it_refuses_a_file_written_by_a_newer_sundial(database):
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["version"] = export.VERSION + 1
    with pytest.raises(export.ExportError, match="newer sundial"):
        export.check(document, 4)


def test_it_refuses_a_file_from_a_newer_schema(database):
    # Migrations only run forwards, so a newer schema cannot be understood, and
    # part-understanding it is how data gets quietly dropped.
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["schema_version"] = 5
    with pytest.raises(export.ExportError, match="schema 5"):
        export.check(document, 4)


def test_it_refuses_a_file_that_is_missing_a_table(database):
    # Absent and empty look identical once imported, so a partial file would delete the
    # part it left out — under a button that promised to restore everything.
    with store.db() as conn:
        document = export.dump(conn, 4)
    del document["tables"]["events"]
    with pytest.raises(export.ExportError, match="missing the events"):
        export.check(document, 4)


def test_it_refuses_a_value_that_is_not_a_scalar(database):
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["tables"]["blocks"] = [{"id": "x", "title": {"nested": True}}]
    with pytest.raises(export.ExportError, match="a dict for"):
        export.check(document, 4)


def test_a_bad_document_is_refused_before_anything_is_written(database):
    seed()
    before = everything()
    with store.db() as conn:
        document = export.dump(conn, 4)
        document["tables"]["blocks"][0]["updated_at"] = ["not", "a", "scalar"]
        with pytest.raises(export.ExportError):
            export.replace(conn, export.check(document, 4))
    assert everything() == before, "a refused import changed the database anyway"


def test_an_import_that_fails_half_way_leaves_the_database_as_it_was(database):
    # The whole point of "replace everything" is that it either happens or it does not.
    # A duplicate primary key is the realistic way to fail after the deletes have run.
    seed()
    before = everything()
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["tables"]["blocks"] = [
        {"id": "dup", "title": "one", "updated_at": "2026-09-21T00:00:00+00:00"},
        {"id": "dup", "title": "two", "updated_at": "2026-09-21T00:00:00+00:00"},
    ]
    document["tables"]["calendars"] = []
    document["tables"]["events"] = []
    document["tables"]["sync_log"] = []

    with store.db() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            export.replace(conn, export.check(document, 4))
    assert everything() == before, "a failed import left the database half replaced"


def test_a_calendar_and_its_events_come_back_across_the_foreign_key(database):
    # `events.calendar_ref` references `calendars.ref`, and the connection turns foreign
    # keys on, so the delete and insert orders are load-bearing rather than decorative.
    seed()
    with store.db() as conn:
        document = json.loads(json.dumps(export.dump(conn, 4)))
        export.replace(conn, export.check(document, 4))
        joined = conn.execute(
            """SELECT calendars.name, events.title AS event
               FROM events JOIN calendars ON calendars.ref = events.calendar_ref"""
        ).fetchall()
    assert [tuple(r) for r in joined] == [("Home", "Dentist")]


def test_an_unknown_column_is_reported_rather_than_dropped(database):
    # The one case where a "successful" import loses something quietly: a column that
    # passes validation and then cannot be inserted. A typo in a hand-made file.
    with store.db() as conn:
        document = export.dump(conn, 4)
        document["tables"]["blocks"] = [
            {"id": "x", "title": "t", "updated_at": "2026-09-21T00:00:00+00:00", "titel": "typo"}
        ]
        assert export.unknown_columns(document, conn) == {"blocks": ["titel"]}


def test_a_future_column_the_table_does_not_know_is_not_silently_accepted(database):
    # Same guard from the other side: a field added by a later version must surface as
    # unknown rather than vanish between validation and insertion.
    with store.db() as conn:
        document = export.dump(conn, 4)
        document["tables"]["calendars"] = [{"ref": "r", "provider": "icloud", "name": "n",
                                            "colour_next_gen": "amber"}]
        assert export.unknown_columns(document, conn) == {"calendars": ["colour_next_gen"]}


# ---- over HTTP, which is how anyone will actually use it ---------------------------------

def test_export_downloads_a_named_file_of_the_right_shape(client):
    seed()
    answer = client.get("/api/export")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == (
        f'attachment; filename="sundial-{app.today()}.json"'
    )
    document = answer.json()
    assert document["format"] == export.FORMAT
    assert document["schema_version"] == 5
    assert len(document["tables"]["blocks"]) == 2
    assert "push_subscriptions" not in document["tables"]


def test_an_import_has_to_mean_it(client):
    # The endpoint can lose everything in one request, so the request has to say so.
    seed()
    before = everything()
    for body in ({"document": {}}, {"confirm": "", "document": {}},
                 {"confirm": "yes", "document": {}}):
        answer = client.post("/api/import", json=body)
        assert answer.status_code == 400
        assert "replaces everything" in answer.json()["detail"]
    assert everything() == before


def test_a_document_that_will_not_import_is_refused_with_a_sentence(client):
    seed()
    before = everything()
    answer = client.post(
        "/api/import",
        json={"confirm": "replace everything", "document": {"format": "someone-elses-app"}},
    )
    assert answer.status_code == 400
    assert "not a sundial export" in answer.json()["detail"]
    assert everything() == before


def test_a_file_with_columns_sundial_does_not_know_is_refused(client):
    seed()
    document = client.get("/api/export").json()
    document["tables"]["blocks"] = [
        {"id": "x", "title": "t", "updated_at": "2026-09-21T00:00:00+00:00", "titel": "typo"}
    ]
    answer = client.post("/api/import", json={"confirm": "replace everything", "document": document})
    assert answer.status_code == 400
    assert "blocks.titel" in answer.json()["detail"]


def test_the_round_trip_works_over_http_and_keeps_a_way_back(client):
    seed()
    before = everything()
    document = client.get("/api/export").json()

    # Wipe it the way an empty install would be, then import the file back.
    with store.db() as conn:
        for name in export.TABLES:
            conn.execute(f"DELETE FROM {name}")

    answer = client.post("/api/import", json={"confirm": "replace everything",
                                              "document": document})
    assert answer.status_code == 200
    answer = answer.json()
    assert answer["replaced"] == {"calendars": 1, "routines": 0, "routine_overrides": 0,
                                  "blocks": 2, "events": 1, "sync_log": 1, "push_sent": 0}
    assert everything() == before

    # The database it replaced is copied first and named in the answer, so a mistaken
    # import is recoverable rather than final.
    kept = pathlib.Path(answer["kept"])
    assert kept.exists() and kept.parent == pathlib.Path(database_file_of(client)).parent
    assert kept.name.startswith("sundial.replaced-")


def test_a_restore_does_not_unsubscribe_the_phone(client):
    seed()
    document = client.get("/api/export").json()
    with store.db() as conn:
        for name in export.TABLES:
            conn.execute(f"DELETE FROM {name}")
    answer = client.post("/api/import", json={"confirm": "replace everything",
                                              "document": document}).json()
    assert answer["left_alone"] == {"push_subscriptions": 1}
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()["n"] == 1


def database_file_of(client):
    """Where the app's own connection says the database is."""
    with store.db() as conn:
        return export.database_file(conn)


def test_a_file_that_contradicts_itself_is_refused_with_a_sentence(client):
    # Two rows with one primary key. SQLite raises IntegrityError, and an unhandled one is a
    # 500 with a stack trace: no sentence, and no way to tell whether the import took.
    seed()
    before = everything()
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["tables"]["blocks"] = [
        {"id": "dup", "title": "one", "updated_at": "2026-09-21T00:00:00+00:00"},
        {"id": "dup", "title": "two", "updated_at": "2026-09-21T00:00:00+00:00"},
    ]
    answer = client.post("/api/import", json={"confirm": "replace everything", "document": document})
    assert answer.status_code == 400, "a contradictory file should be a refusal, not a 500"
    detail = answer.json()["detail"]
    assert "contradicts itself" in detail
    assert "blocks" in detail, "the sentence should name what SQLite objected to"
    assert "Nothing was changed" in detail
    assert everything() == before


def test_a_file_naming_a_calendar_it_does_not_carry_is_refused(client):
    # Foreign keys are on, so an orphaned event cannot land. It is the same refusal, reached
    # from the other direction, and it must not leave the earlier tables already deleted.
    seed()
    before = everything()
    with store.db() as conn:
        document = export.dump(conn, 4)
    document["tables"]["calendars"] = []
    document["tables"]["events"] = [
        {"id": "e9", "calendar_ref": "gone", "provider": "icloud", "uid": "u9",
         "title": "Orphan", "start_utc": "2026-09-21T17:00:00+00:00",
         "end_utc": "2026-09-21T18:00:00+00:00", "updated_at": "2026-09-20T00:00:00+00:00"},
    ]
    answer = client.post("/api/import", json={"confirm": "replace everything", "document": document})
    assert answer.status_code == 400
    assert "contradicts itself" in answer.json()["detail"]
    assert everything() == before, "a refused import left the earlier tables emptied"
