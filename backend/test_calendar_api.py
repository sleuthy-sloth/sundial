"""The HTTP surface of calendar sync: what it answers when nothing is connected, and what
it refuses. The sync itself is tested against a scripted server in test_calendar_service.py;
here the engine is stubbed, because a test must never reach out to iCloud.
"""

import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SUNDIAL_DB", str(pathlib.Path(tempfile.mkdtemp()) / "api-tests.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as sundial  # noqa: E402
import calendar_service  # noqa: E402
import store  # noqa: E402

HOME_REF = "/123456789/calendars/home/"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setenv("SUNDIAL_ICLOUD_ENV", str(tmp_path / "icloud.env"))
    sundial.bootstrap()
    yield


@pytest.fixture
def client():
    return TestClient(sundial.app)


def add_calendar(ref=HOME_REF, name="Home", enabled=1):
    with store.db() as conn:
        conn.execute(
            """INSERT INTO calendars (ref, provider, name, colour, enabled, writable, ctag, last_sync)
               VALUES (?, 'icloud', ?, 'sky', ?, 0, 'ctag-1', '2026-09-21T10:00:00+00:00')""",
            (ref, name, enabled),
        )


def add_event(uid="dentist-1", day="2026-09-21", hour=14, title="Dentist", ref=HOME_REF):
    start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
    end = start + timedelta(hours=1)
    with store.db() as conn:
        conn.execute(
            """INSERT INTO events (id, calendar_ref, provider, uid, recurrence_id, title, location,
                 notes, start_utc, end_utc, all_day, rrule, raw_ics, status, etag, sequence, updated_at)
               VALUES (?, ?, 'icloud', ?, '', ?, '', '', ?, ?, 0, NULL, NULL, 'CONFIRMED', 'e', 0, ?)""",
            (f"{ref}|{uid}|", ref, uid, title, start.isoformat(), end.isoformat(),
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


# ------------------------------------------------------------------- no credentials yet


def test_calendars_answers_that_nothing_is_connected_rather_than_failing(client):
    body = client.get("/api/calendars").json()
    assert body["configured"] is False
    assert "icloud.env" in body["why"]
    assert body["calendars"] == [] and body["last_sync"] is None


def test_syncing_with_nothing_connected_is_a_refusal_with_the_instruction(client):
    response = client.post("/api/calendars/sync")
    assert response.status_code == 400
    assert "icloud.env" in response.json()["detail"]


# ------------------------------------------------------------------- with a calendar


def test_calendars_lists_what_is_stored_with_its_event_count(client):
    add_calendar()
    add_event()
    add_event(uid="lunch-1", title="Lunch")

    body = client.get("/api/calendars").json()
    assert [c["name"] for c in body["calendars"]] == ["Home"]
    assert body["calendars"][0]["events"] == 2
    assert body["last_sync"] == "2026-09-21T10:00:00+00:00"


def test_events_for_a_day_are_the_instants_that_land_in_it(client):
    add_calendar()
    add_event(day="2026-09-21", hour=14)
    add_event(uid="next-1", day="2026-09-22", hour=9, title="Tomorrow")

    body = client.get("/api/events?day=2026-09-21").json()
    assert body["day"] == "2026-09-21"
    assert [e["title"] for e in body["events"]] == ["Dentist"]
    assert body["count"] == 1


def test_events_default_to_today(client):
    body = client.get("/api/events").json()
    assert body["day"] == sundial.today()


def test_a_malformed_day_is_refused_not_guessed(client):
    for bad in ("20260921", "21-09-2026", "2026-13-01"):
        response = client.get(f"/api/events?day={bad}")
        assert response.status_code == 400, bad


def test_a_calendar_can_be_switched_off_and_back_on(client):
    add_calendar()
    assert client.patch("/api/calendars", json={"ref": HOME_REF, "enabled": False}).status_code == 200
    assert client.get("/api/calendars").json()["calendars"][0]["enabled"] == 0

    client.patch("/api/calendars", json={"ref": HOME_REF, "enabled": True})
    assert client.get("/api/calendars").json()["calendars"][0]["enabled"] == 1


def test_switching_off_something_that_does_not_exist_is_a_404(client):
    response = client.patch("/api/calendars", json={"ref": "/nope/", "enabled": False})
    assert response.status_code == 404


# ------------------------------------------------------------------- the sync itself


def test_the_sync_route_passes_the_staleness_it_was_given(client, monkeypatch):
    seen = {}

    def fake_sync(*, if_stale_seconds=0, **_):
        seen["if_stale_seconds"] = if_stale_seconds
        return {"calendars": [], "totals": {"added": 0, "updated": 0, "removed": 0, "errors": 0}}

    monkeypatch.setattr(sundial.calendar_service, "sync", fake_sync)

    assert client.post("/api/calendars/sync", json={"if_stale_seconds": 900}).status_code == 200
    assert seen["if_stale_seconds"] == 900
    assert client.post("/api/calendars/sync").status_code == 200
    assert seen["if_stale_seconds"] == 0, "no body means sync now"


def test_a_sync_that_cannot_reach_the_server_is_a_gateway_error(client, monkeypatch):
    def refuse(**_):
        raise sundial.CalDavError("caldav.icloud.com refused those credentials (401)")

    monkeypatch.setattr(sundial.calendar_service, "sync", refuse)
    response = client.post("/api/calendars/sync")
    assert response.status_code == 502
    assert "401" in response.json()["detail"]


def test_the_credentials_path_is_a_setting_not_a_parameter(client, monkeypatch, tmp_path):
    """Nothing in the API accepts a username or a password: they live in a file the server
    reads, so they never travel through a request or a log."""
    monkeypatch.setattr(
        sundial.calendar_service, "sync",
        lambda **_: {"calendars": [], "totals": {"added": 0, "updated": 0, "removed": 0, "errors": 0}},
    )
    for path in ("/api/calendars", "/api/calendars/sync"):
        schema = client.get("/api/openapi.json").json()
    parameters = schema["paths"]["/api/calendars/sync"]["post"].get("parameters", [])
    body = schema["components"]["schemas"]["SyncIn"]["properties"]
    assert set(body) == {"if_stale_seconds"}
    assert not any("password" in str(p).lower() for p in parameters)
