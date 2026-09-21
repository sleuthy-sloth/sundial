"""The HTTP surface of calendar sync: what it answers when nothing is connected, and what
it refuses. The sync itself is tested against a scripted server in test_calendar_service.py;
here the engine is stubbed, because a test must never reach out to iCloud.
"""

import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("SUNDIAL_DB", str(pathlib.Path(tempfile.mkdtemp()) / "api-tests.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as sundial  # noqa: E402
import calendar_service  # noqa: E402
import google_oauth  # noqa: E402
import store  # noqa: E402

HOME_REF = "/123456789/calendars/home/"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setenv("SUNDIAL_ICLOUD_ENV", str(tmp_path / "icloud.env"))
    # Both providers, always: a test that leaves one at the developer's real path is a test
    # that reads their credentials.
    monkeypatch.setenv("SUNDIAL_GOOGLE_ENV", str(tmp_path / "google.env"))
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


# --------------------------------------------------------------- which providers exist


def test_the_calendar_list_says_which_providers_are_configured(client):
    providers = {p["provider"]: p for p in client.get("/api/calendars").json()["providers"]}
    assert set(providers) == {"icloud", "google"}
    assert providers["icloud"]["configured"] is False
    assert "icloud.env" in providers["icloud"]["why"]
    assert providers["google"]["configured"] is False
    assert providers["google"]["coming_soon"] is True


def test_icloud_is_the_answer_the_rail_reads(tmp_path, client):
    """`configured` stays the iCloud answer: it is what the Sync control reads, and iCloud is
    the provider that ships."""
    (tmp_path / "icloud.env").write_text("ICLOUD_USERNAME=a@b.c\nICLOUD_APP_PASSWORD=xxxx\n",
                                         encoding="utf-8")
    body = client.get("/api/calendars").json()
    assert body["configured"] is True and body["why"] == ""
    assert {p["provider"]: p["configured"] for p in body["providers"]}["icloud"] is True


def test_a_whole_provider_failing_has_somewhere_to_be_seen(client):
    """A listing failure has no calendar row to hang on, so without this the rail could only
    say that nothing arrived, not why."""
    with store.db() as conn:
        conn.execute(
            """INSERT INTO sync_log (at, provider, calendar_ref, uid, action, detail)
               VALUES ('2026-09-21T10:00:00+00:00', 'google', NULL, NULL, 'error',
                       'Google answered 503: Backend Error')"""
        )
    google = {p["provider"]: p for p in client.get("/api/calendars").json()["providers"]}["google"]
    assert google["last_error"] == "Google answered 503: Backend Error"


# --------------------------------------------------------------- the consent flow

GOOGLE_ENV = "GOOGLE_CLIENT_ID=1234.apps.googleusercontent.com\nGOOGLE_CLIENT_SECRET=shh\n"


def configure_google(tmp_path, extra: str = ""):
    path = tmp_path / "google.env"
    path.write_text(GOOGLE_ENV + extra, encoding="utf-8")
    return path


def test_the_consent_flow_is_refused_honestly_before_it_is_set_up(client):
    response = client.get("/oauth/google/start", follow_redirects=False)
    assert response.status_code == 400
    assert "google.env" in response.json()["detail"]


def test_the_consent_screen_asks_for_read_only_and_nothing_else(tmp_path, client):
    configure_google(tmp_path)
    response = client.get("/oauth/google/start", follow_redirects=False)
    assert response.status_code == 302

    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
    scopes = query["scope"].split()
    assert scopes[0] == "https://www.googleapis.com/auth/calendar.readonly"
    assert "https://www.googleapis.com/auth/calendar" not in scopes
    assert query["code_challenge_method"] == "S256" and query["code_challenge"]
    assert query["access_type"] == "offline" and query["state"]
    assert query["redirect_uri"].endswith("/oauth/google/callback")


def test_the_callback_answers_as_a_page_and_not_as_the_app(client):
    """These two routes are reached by a browser, and the SPA is mounted on / — so this also
    checks the mount above has not swallowed them."""
    # No code is answered before the state is even looked at, which is also what keeps this
    # from confirming whether a guessed state was real.
    bare = client.get("/oauth/google/callback?state=never-started")
    assert bare.status_code == 200
    assert bare.headers["content-type"].startswith("text/html")
    assert "authorization code" in bare.text
    assert '<div id="root"' not in bare.text, "that is the app, not the answer"

    guessed = client.get("/oauth/google/callback?code=x&state=never-started")
    assert guessed.status_code == 200
    assert "expired" in guessed.text.lower()
    assert '<div id="root"' not in guessed.text


def test_a_state_we_never_issued_is_not_accepted(tmp_path, client):
    configure_google(tmp_path)
    response = client.get("/oauth/google/callback?code=stolen&state=guessed")
    assert response.status_code == 200
    assert "expired" in response.text.lower() or "not one we started" in response.text


def test_google_refusing_is_reported_as_google_refusing(tmp_path, client):
    configure_google(tmp_path)
    response = client.get("/oauth/google/callback?error=access_denied")
    assert "access_denied" in response.text


def test_connecting_writes_the_refresh_token_and_says_so(tmp_path, client, monkeypatch):
    """The whole handshake, minus Google: start, come back with a code, end up connected."""
    path = configure_google(tmp_path)
    started = client.get("/oauth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]

    seen = {}

    def fake_exchange(configuration, *, code, verifier, redirect_uri, **kw):
        seen.update(code=code, verifier=verifier, redirect_uri=redirect_uri)
        return google_oauth.Tokens(access_token="at", expires_at=0.0,
                                   refresh_token="1//refresh", account="steven@example.com")

    monkeypatch.setattr(sundial.google_oauth, "exchange", fake_exchange)
    response = client.get(f"/oauth/google/callback?code=the-code&state={state}")

    assert response.status_code == 200 and "Connected" in response.text
    assert "steven@example.com" in response.text

    saved = google_oauth.load_configuration(path)
    assert saved.connected and saved.refresh_token == "1//refresh"
    assert saved.account == "steven@example.com"
    assert seen["code"] == "the-code" and seen["verifier"], "the PKCE verifier travelled"

    # Nothing that could be used arrives back in a page somebody might screenshot.
    assert "the-code" not in response.text
    assert "1//refresh" not in response.text
    assert "shh" not in response.text


def test_a_second_callback_with_the_same_link_is_refused(tmp_path, client, monkeypatch):
    """Single use, or a link in a browser history is a link somebody else can replay."""
    configure_google(tmp_path)
    started = client.get("/oauth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    monkeypatch.setattr(sundial.google_oauth, "exchange", lambda *a, **kw: google_oauth.Tokens(
        access_token="at", expires_at=0.0, refresh_token="1//one", account=""))
    first = client.get(f"/oauth/google/callback?code=c&state={state}")
    second = client.get(f"/oauth/google/callback?code=c&state={state}")
    assert "Connected" in first.text
    assert "Connected" not in second.text


# --------------------------------------------------------- typing a credential in the panel

ICLOUD_FIELDS = {"ICLOUD_USERNAME": "steve@example.com", "ICLOUD_APP_PASSWORD": "abcd-efgh-ijkl-mnop"}


def test_connecting_from_the_panel_writes_the_file_and_answers_with_the_state(tmp_path, client):
    response = client.post("/api/calendars/credentials",
                           json={"provider": "icloud", "fields": ICLOUD_FIELDS})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "icloud"
    assert body["configured"] is True and body["why"] == ""

    written = (tmp_path / "icloud.env").read_text(encoding="utf-8")
    assert "ICLOUD_APP_PASSWORD=abcd-efgh-ijkl-mnop" in written


def test_the_reply_never_carries_back_what_was_sent(tmp_path, client):
    """A response body is the easiest place for a secret to end up: it gets logged by
    whatever is in front, shown in dev tools, and screenshotted."""
    response = client.post("/api/calendars/credentials",
                           json={"provider": "icloud", "fields": ICLOUD_FIELDS})
    assert "abcd-efgh-ijkl-mnop" not in response.text


def test_a_bad_key_says_which_key_and_never_the_value(tmp_path, client):
    response = client.post("/api/calendars/credentials", json={
        "provider": "icloud",
        "fields": {"ICLOUD_USERNAME": "steve@example.com", "ICLOUD_APP_PASSWROD": "abcd-efgh"},
    })
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "ICLOUD_APP_PASSWROD" in detail, "name it: the person typed it"
    assert "abcd-efgh" not in detail, "and never repeat what was typed into it"
    assert not (tmp_path / "icloud.env").exists()


def test_the_calendar_list_reports_it_connected_afterwards(tmp_path, client):
    client.post("/api/calendars/credentials", json={"provider": "icloud", "fields": ICLOUD_FIELDS})

    body = client.get("/api/calendars").json()
    assert body["configured"] is True and body["why"] == ""
    assert {p["provider"]: p["configured"] for p in body["providers"]}["icloud"] is True


def test_connecting_is_not_a_claim_that_it_worked(tmp_path, client):
    """Saving says the file is right, not that Apple accepted it — the sync is what finds
    that out, and a panel that said "connected" before then would be guessing."""
    body = client.post("/api/calendars/credentials",
                       json={"provider": "icloud", "fields": ICLOUD_FIELDS}).json()
    assert body["configured"] is True and body["why"] == ""

    # The file is right; nothing has been read. The panel learns whether the password works
    # from the sync it runs next, which is the only thing that can answer it.
    listing = client.get("/api/calendars").json()
    assert listing["last_sync"] is None and listing["calendars"] == []


def test_a_google_client_can_be_filled_in_and_still_reads_as_coming_soon(tmp_path, client):
    """The console step produces these two values before anything else can happen, so this
    half of it has to work even while the interface keeps Google switched off."""
    response = client.post("/api/calendars/credentials", json={
        "provider": "google",
        "fields": {"GOOGLE_CLIENT_ID": "1234.apps.googleusercontent.com",
                   "GOOGLE_CLIENT_SECRET": "shh"},
    })
    assert response.status_code == 200
    assert "shh" not in response.text

    # Saved and connected are different facts. This is the half that a console visit
    # produces, and the half that is missing is the one that needs a person.
    body = response.json()
    assert body["configured"] is False
    assert "not connected yet" in body["why"]
    assert "GOOGLE_CLIENT_ID=1234.apps.googleusercontent.com" in (tmp_path / "google.env").read_text()

    google = {p["provider"]: p for p in client.get("/api/calendars").json()["providers"]}["google"]
    assert google["configured"] is False and google["coming_soon"] is True
    assert client.get("/api/calendars").json()["configured"] is False, "iCloud is still the rail's answer"


def test_an_unknown_provider_is_a_400_rather_than_a_silent_nothing(tmp_path, client):
    response = client.post("/api/calendars/credentials",
                           json={"provider": "fastmail", "fields": ICLOUD_FIELDS})
    assert response.status_code == 400
    assert "fastmail" in response.json()["detail"]
