"""The engine, against a CalDAV server that is scripted but real: the client, the protocol
and the XML all run, and only the socket is missing.

The tests that matter most are the ones about what a sync does *not* do — a fetch that
failed must not read as "these events stopped existing", and a row the server was never
asked about must survive being absent from an answer.
"""

import json
import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SUNDIAL_DB", str(pathlib.Path(tempfile.mkdtemp()) / "service-tests.db"))

import httpx  # noqa: E402
import pytest  # noqa: E402

import app as sundial  # noqa: E402
import caldav  # noqa: E402
import calendar_service as service  # noqa: E402
import store  # noqa: E402

SECRET = "abcd-efgh-ijkl-mnop"
HOME_REF = "/123456789/calendars/home/"

PRINCIPAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:"><response><href>/</href><propstat><prop>
<current-user-principal><href>/123456789/principal/</href></current-user-principal>
</prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""

HOME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><response>
<href>/123456789/principal/</href><propstat><prop>
<C:calendar-home-set><href>/123456789/calendars/</href></C:calendar-home-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""


def ics(uid: str, summary: str, start: str, end: str, extra: str = "") -> str:
    body = (
        f"BEGIN:VCALENDAR&#13;\nVERSION:2.0&#13;\nBEGIN:VEVENT&#13;\nUID:{uid}&#13;\n"
        f"SUMMARY:{summary}&#13;\nDTSTART:{start}&#13;\nDTEND:{end}&#13;\n{extra}"
        f"END:VEVENT&#13;\nEND:VCALENDAR&#13;\n"
    )
    return body


def in_days(days: int, hour: int = 14) -> str:
    day = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y%m%d")
    return f"{day}T{hour:02d}0000Z"


def end_of(start: str) -> str:
    return start[:9] + f"{(int(start[9:11]) + 1):02d}0000Z"


class FakeServer:
    """A calendar server whose answers this test can change between syncs."""

    def __init__(self) -> None:
        self.calendars: dict[str, dict] = {
            HOME_REF: {
                "name": "Home",
                "colour": "#3F6B8AFF",
                "ctag": "ctag-1",
                "objects": {},  # href → (etag, ics body)
            }
        }
        self.reports: list[str] = []
        self.listings = 0
        self.fail_report: int | None = None
        self.fail_listing: int | None = None

    def event(self, uid: str, summary: str, start: str, ref: str = HOME_REF, extra: str = "") -> None:
        self.calendars[ref]["objects"][f"{ref}{uid}.ics"] = (
            f"etag-{uid}-{summary.replace(' ', '')}",
            ics(uid, summary, start, end_of(start), extra),
        )

    def drop(self, uid: str, ref: str = HOME_REF) -> None:
        self.calendars[ref]["objects"].pop(f"{ref}{uid}.ics", None)

    def bump(self, ref: str = HOME_REF) -> None:
        self.calendars[ref]["ctag"] += "+"

    # -- the server itself

    def calendars_xml(self) -> str:
        responses = []
        for ref, calendar in self.calendars.items():
            responses.append(
                f"""<response><href>{ref}</href><propstat><prop>
<resourcetype><collection/><C:calendar/></resourcetype>
<displayname>{calendar['name']}</displayname>
<A:calendar-color>{calendar['colour']}</A:calendar-color>
<CS:getctag>{calendar['ctag']}</CS:getctag>
<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
<current-user-privilege-set><privilege><read/></privilege></current-user-privilege-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>"""
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<multistatus xmlns="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:CS="http://calendarserver.org/ns/" '
            'xmlns:A="http://apple.com/ns/ical/">' + "".join(responses) + "</multistatus>"
        )

    def events_xml(self, ref: str) -> str:
        responses = []
        for href, (etag, body) in self.calendars[ref]["objects"].items():
            responses.append(
                f'<response><href>{href}</href><propstat><prop><getetag>"{etag}"</getetag>'
                f"<C:calendar-data>{body}</C:calendar-data></prop>"
                f"<status>HTTP/1.1 200 OK</status></propstat></response>"
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<multistatus xmlns="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">' + "".join(responses) + "</multistatus>"
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "PROPFIND" and path == "/":
            return httpx.Response(207, content=PRINCIPAL_XML.encode())
        if request.method == "PROPFIND" and path == "/123456789/principal/":
            return httpx.Response(207, content=HOME_XML.encode())
        if request.method == "PROPFIND" and path == "/123456789/calendars/":
            self.listings += 1
            if self.fail_listing:
                return httpx.Response(self.fail_listing, content=b"")
            return httpx.Response(207, content=self.calendars_xml().encode())
        if request.method == "REPORT":
            self.reports.append(path)
            if self.fail_report:
                return httpx.Response(self.fail_report, content=b"")
            if path in self.calendars:
                return httpx.Response(207, content=self.events_xml(path).encode())
        return httpx.Response(404, content=b"no such route")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def client(self) -> caldav.CalDavClient:
        return caldav.CalDavClient(
            caldav.Credentials("steven@example.com", SECRET, "https://caldav.icloud.com/"),
            transport=self.transport(),
        )


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "calendar-tests.db")
    monkeypatch.setenv("SUNDIAL_ICLOUD_ENV", str(tmp_path / "icloud.env"))
    sundial.bootstrap()
    yield


def sync(server: FakeServer, **kw) -> dict:
    return service.sync(client=server.client(), **kw)


def rows(ref: str = HOME_REF) -> list:
    with store.db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM events WHERE calendar_ref = ?", (ref,))]


def log_actions() -> list[str]:
    return [entry["action"] for entry in service.recent_log(50)]


# ------------------------------------------------------------------- the happy path


def test_a_first_sync_stores_the_calendar_and_its_events():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    result = sync(server)

    stored = service.calendars()
    assert [c["name"] for c in stored] == ["Home"]
    assert stored[0]["colour"] == "sky"
    assert stored[0]["enabled"] == 1
    assert stored[0]["ctag"] == "ctag-1"
    assert stored[0]["last_sync"] and stored[0]["last_error"] is None
    assert stored[0]["events"] == 1

    assert [r["title"] for r in rows()] == ["Dentist"]
    assert result["totals"] == {"added": 1, "updated": 0, "removed": 0, "errors": 0}
    assert result["calendars"][0]["added"] == 1
    assert "import" in log_actions()


def test_syncing_twice_is_not_importing_twice():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)

    server.bump()  # the ctag moved, so the window is fetched again
    server.event("dentist-1", "Dentist", in_days(1))  # unchanged, e.g. a different ETag
    result = sync(server)

    assert len(rows()) == 1
    assert result["totals"] == {"added": 0, "updated": 0, "removed": 0, "errors": 0}
    assert result["calendars"][0]["unchanged"] == 1


def test_an_unchanged_ctag_means_no_fetch_at_all():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)
    before = len(server.reports)

    result = sync(server)

    assert len(server.reports) == before, "nothing changed, so nothing was asked for"
    assert result["calendars"][0]["skipped"] is True


def test_a_changed_event_is_updated_and_the_field_is_named_in_the_log():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)

    # SEQUENCE is how a calendar says "this is a new revision of the same event", and is
    # what decides the conflict without either side depending on the clock.
    server.event("dentist-1", "Dentist (moved)", in_days(2), extra="SEQUENCE:1&#13;\n")
    server.bump()
    result = sync(server)

    assert [r["title"] for r in rows()] == ["Dentist (moved)"]
    assert result["totals"]["updated"] == 1
    with store.db() as conn:
        detail = conn.execute(
            "SELECT detail FROM sync_log WHERE action = 'update' ORDER BY id DESC LIMIT 1"
        ).fetchone()["detail"]
    assert "title" in detail and "start_utc" in detail


def test_an_edit_in_the_same_second_is_deferred_rather_than_clobbering():
    """The inherited rule: a tie goes to the local copy. A remote change with the same
    SEQUENCE arriving in the same second as our own sync is not applied this round — the
    clock cannot separate them. It is not lost: the next sync sees the same difference with
    a later timestamp and takes it, and the ETag has already been recorded."""
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)

    server.event("dentist-1", "Dentist (moved)", in_days(1))  # no SEQUENCE bump, no waiting
    server.bump()
    sync(server)

    assert [r["title"] for r in rows()] == ["Dentist"], "same second, so the tie holds"
    assert service.calendars()[0]["last_error"] is None


def test_an_event_deleted_at_the_server_is_deleted_here_and_logged():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    server.event("lunch-1", "Lunch", in_days(2))
    sync(server)

    server.drop("lunch-1")
    server.bump()
    result = sync(server)

    assert [r["title"] for r in rows()] == ["Dentist"]
    assert result["totals"]["removed"] == 1
    removed = [entry for entry in service.recent_log(50) if entry["action"] == "remove"]
    assert removed and removed[0]["uid"] == "lunch-1"
    assert "no longer on the server" in removed[0]["detail"]


def test_a_cancellation_is_an_instruction_to_remove():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)

    server.event("dentist-1", "Dentist", in_days(1), extra="STATUS:CANCELLED&#13;\n")
    server.bump()
    result = sync(server)

    assert rows() == []
    assert result["totals"]["removed"] == 1


# ------------------------------------------------------------------- the safety rules


def test_a_failed_fetch_deletes_nothing_at_all():
    """The whole point. A REPORT that answered 500 says nothing about what exists."""
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    server.event("lunch-1", "Lunch", in_days(2))
    sync(server)

    server.fail_report = 500
    server.bump()
    result = sync(server)

    assert len(rows()) == 2, "an error must never read as 'these events are gone'"
    assert result["totals"]["removed"] == 0
    assert result["calendars"][0]["error"] and "500" in result["calendars"][0]["error"]
    assert "remove" not in log_actions()

    stored = service.calendars()[0]
    assert stored["last_error"] and "500" in stored["last_error"]
    assert stored["ctag"] == "ctag-1", "a failed sync must not advance the cursor"


def test_an_error_on_one_calendar_does_not_stop_the_other():
    server = FakeServer()
    server.calendars["/123456789/calendars/work/"] = {
        "name": "Work", "colour": "#FF9500FF", "ctag": "w-1", "objects": {},
    }
    server.event("dentist-1", "Dentist", in_days(1))
    server.event("standup-1", "Standup", in_days(1), ref="/123456789/calendars/work/")
    sync(server)
    server.bump("/123456789/calendars/work/")  # or it would be skipped, not fetched

    original = server.handler

    def handler(request):
        if request.method == "REPORT" and request.url.path == "/123456789/calendars/work/":
            return httpx.Response(503, content=b"")
        return original(request)

    partial = service.sync(
        client=caldav.CalDavClient(
            caldav.Credentials("steven@example.com", SECRET, "https://caldav.icloud.com/"),
            transport=httpx.MockTransport(handler),
        )
    )
    by_name = {c["name"]: c for c in partial["calendars"]}
    assert by_name["Home"]["skipped"] is True
    assert by_name["Work"]["error"] and "503" in by_name["Work"]["error"]
    assert partial["totals"]["errors"] == 1
    assert len(rows("/123456789/calendars/work/")) == 1, "the other calendar's data stands"


def test_an_event_outside_the_window_is_never_reconciled():
    """Stored from an earlier, wider window; the server is not asked about it, so its
    absence from the answer means nothing."""
    server = FakeServer()
    old_start = in_days(-40)
    with store.db() as conn:
        conn.execute(
            """INSERT INTO calendars (ref, provider, name, colour, enabled, writable, ctag, last_sync)
               VALUES (?, 'icloud', 'Home', 'sky', 1, 0, 'ctag-1', NULL)""",
            (HOME_REF,),
        )
        conn.execute(
            """INSERT INTO events (id, calendar_ref, provider, uid, recurrence_id, title, location,
                 notes, start_utc, end_utc, all_day, rrule, raw_ics, status, etag, sequence, updated_at)
               VALUES ('old', ?, 'icloud', 'old-1', '', 'Long past', '', '', ?, ?, 0, NULL, NULL,
                       'CONFIRMED', 'e', 0, '2026-01-01T00:00:00+00:00')""",
            (HOME_REF, f"{old_start[:4]}-{old_start[4:6]}-{old_start[6:8]}T14:00:00+00:00",
             f"{old_start[:4]}-{old_start[4:6]}-{old_start[6:8]}T15:00:00+00:00"),
        )

    server.bump()  # force a real fetch
    sync(server)

    assert [r["title"] for r in rows()] == ["Long past"]


def test_a_series_that_started_long_ago_is_not_deleted_when_the_window_moves_past_it():
    """Its first occurrence is outside the window, so no query asked about it."""
    server = FakeServer()
    start = in_days(-30)
    server.event("weekly-1", "Weekly", start, extra="RRULE:FREQ=WEEKLY&#13;\n")
    sync(server)
    assert len(rows()) == 1

    # Next sync: the server returns only what overlaps the window — the master itself is
    # still returned while its rule reaches into it, but the point is that its start is
    # outside, which is what makes it ineligible for removal.
    server.drop("weekly-1")
    server.bump()
    sync(server)

    assert len(rows()) == 1, "a series is not a deletion candidate from outside the window"


def test_a_calendar_listing_that_comes_back_empty_disables_nothing():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)

    server.calendars = {}  # the listing itself goes wrong, not just one calendar
    sync(server)

    stored = service.calendars()[0]
    assert stored["enabled"] == 1, "an empty listing is a bad day, not a deleted calendar"
    assert len(rows()) == 1
    assert "error" in log_actions()


def test_a_disabled_calendar_is_not_fetched():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)
    with store.db() as conn:
        conn.execute("UPDATE calendars SET enabled = 0")
    server.bump()
    before = len(server.reports)

    sync(server)

    assert len(server.reports) == before


# ------------------------------------------------------------------- asking politely


def test_if_stale_does_not_ask_twice_in_a_row():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)
    requests_before = len(server.reports)

    result = service.sync(client=server.client(), if_stale_seconds=900)

    assert result["skipped"] == "fresh"
    assert len(server.reports) == requests_before
    assert result["last_sync"]


def test_if_stale_still_syncs_when_the_last_one_is_old():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)
    with store.db() as conn:
        conn.execute("UPDATE calendars SET last_sync = '2020-01-01T00:00:00+00:00'")
    server.bump()

    result = service.sync(client=server.client(), if_stale_seconds=900)

    assert result.get("skipped") is None, "the last sync was years ago, so it looked"
    assert result["calendars"][0]["skipped"] is False
    assert result["calendars"][0]["unchanged"] == 1, "and found the same event"


# ------------------------------------------------------------------- credentials


def test_no_credentials_is_a_normal_state_with_a_usable_message():
    credentials, why = service.configuration()
    assert credentials is None
    assert "icloud.env" in why


def test_credentials_are_read_fresh_every_time(tmp_path):
    assert service.configuration()[0] is None

    service.config_path().write_text(
        f"ICLOUD_USERNAME=steven@example.com\nICLOUD_APP_PASSWORD={SECRET}\n", encoding="utf-8"
    )
    credentials, why = service.configuration()

    assert why == "" and credentials is not None
    assert credentials.password == SECRET


def test_syncing_with_no_credentials_refuses_instead_of_guessing():
    with pytest.raises(caldav.NotConfigured) as caught:
        service.sync()
    assert "icloud.env" in str(caught.value)


def test_the_password_reaches_nothing_that_is_stored_or_shown(tmp_path):
    """Everything a sync writes, and the one thing none of it may contain."""
    service.config_path().write_text(
        f"ICLOUD_USERNAME=steven@example.com\nICLOUD_APP_PASSWORD={SECRET}\n", encoding="utf-8"
    )
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    server.fail_report = 500  # so an error message is produced and stored too

    result = service.sync(transport=server.transport())  # one calendar fails, the rest runs
    assert result["calendars"][0]["error"], "the failure is reported, not swallowed"

    shown = json.dumps(
        {"result": result, "calendars": service.calendars(), "log": service.recent_log(50)}
    )
    assert SECRET not in shown
    assert SECRET not in (service.calendars()[0]["last_error"] or "")
    assert SECRET not in store.DB_PATH.read_bytes().decode("utf-8", "ignore")


# ------------------------------------------------------------------- reading back


def test_events_between_returns_what_falls_in_the_window():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1, hour=14))
    server.event("far-1", "Next year", in_days(300))
    sync(server)

    now = datetime.now(timezone.utc)
    found = service.events_between(now - timedelta(days=1), now + timedelta(days=7))

    assert [e["title"] for e in found] == ["Dentist"]


def test_events_between_expands_a_weekly_series():
    server = FakeServer()
    server.event("weekly-1", "Standup", in_days(1, hour=9), extra="RRULE:FREQ=WEEKLY&#13;\n")
    sync(server)

    now = datetime.now(timezone.utc)
    found = service.events_between(now - timedelta(days=1), now + timedelta(days=21))

    assert len(found) == 3, "three weeks of a weekly meeting, not one master row"
    assert [e["start_utc"] for e in found] == sorted(e["start_utc"] for e in found)
    assert all(e["title"] == "Standup" for e in found)


def test_events_between_ignores_a_disabled_calendar():
    server = FakeServer()
    server.event("dentist-1", "Dentist", in_days(1))
    sync(server)
    with store.db() as conn:
        conn.execute("UPDATE calendars SET enabled = 0")

    now = datetime.now(timezone.utc)
    assert service.events_between(now - timedelta(days=1), now + timedelta(days=7)) == []
