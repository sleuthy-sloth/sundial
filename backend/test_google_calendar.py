"""The Google transport, against scripted JSON.

No network and no Google account. Every reply here is a document the API really sends —
a page of calendars, a page of occurrences, a 403 that means the API was never switched
on — because the interesting failures are the ones that cannot be reproduced on demand
against the real thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

import google_calendar as gc

START = datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc)
END = START + timedelta(days=67)


class FakeAuth:
    """Stands in for GoogleAuth. A different token every time, so a header built once at
    construction instead of per request gets caught rather than working by accident."""

    def __init__(self) -> None:
        self.calls = 0

    def headers(self) -> dict:
        self.calls += 1
        return {"Authorization": f"Bearer at-{self.calls}"}


def scripted(pages: list[dict], status: int = 200):
    """(transport, requests) — one reply per request, in order, and what was asked for."""
    seen: list[httpx.Request] = []
    replies = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = replies.pop(0) if replies else {}
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), seen


def calendar(**fields) -> dict:
    base = {"id": "steve@example.com", "summary": "Personal", "backgroundColor": "#3F6B8A",
            "accessRole": "owner"}
    base.update(fields)
    return base


def events(items: list[dict], **fields) -> dict:
    payload = {"items": items}
    payload.update(fields)
    return payload


def session(pages: list[dict], status: int = 200):
    transport, seen = scripted(pages, status=status)
    return gc.GoogleCalendar(FakeAuth(), transport=transport), seen


def query_of(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}


# ------------------------------------------------------------------ the calendar list


def test_the_calendar_list_keeps_what_a_person_recognises():
    cal, _ = session([events([calendar()])])
    found = cal.calendars()

    assert len(found) == 1
    assert found[0]["ref"] == "steve@example.com"
    assert found[0]["name"] == "Personal"
    assert found[0]["provider"] == "google"
    assert found[0]["colour"] == "sky"       # #3F6B8A is sundial's sky
    assert found[0]["writable"] == 1


def test_a_name_the_person_changed_wins():
    """summaryOverride is what they renamed it to; summary is what it is called."""
    cal, _ = session([events([calendar(summary="Work", summaryOverride="Day job")])])
    assert cal.calendars()[0]["name"] == "Day job"


def test_hidden_and_deleted_calendars_are_left_alone():
    """Hidden is a decision they already made in Google. Importing it disabled would look
    like sundial's own setting and quietly undo it."""
    cal, _ = session([events([
        calendar(id="visible"),
        calendar(id="hidden", hidden=True),
        calendar(id="deleted", deleted=True),
        {"id": "", "summary": "nameless"},
    ])])
    assert [c["ref"] for c in cal.calendars()] == ["visible"]


def test_the_write_flag_follows_the_access_role():
    for role, expected in (("owner", 1), ("writer", 1), ("reader", 0), ("freeBusyReader", 0)):
        cal, _ = session([events([calendar(accessRole=role)])])
        assert cal.calendars()[0]["writable"] == expected, role


def test_a_calendar_carries_no_ctag_so_the_window_is_always_fetched():
    """A calendarList etag does not move when events change, so it must never be used to
    skip a fetch. The engine only skips when a ctag matches; None means never."""
    cal, _ = session([events([calendar(etag='"meta-etag"')])])
    assert cal.calendars()[0]["ctag"] is None


def test_calendars_are_followed_across_pages():
    cal, seen = session([
        events([calendar(id="one")], nextPageToken="page-2"),
        events([calendar(id="two")]),
    ])
    found = cal.calendars()
    assert [c["ref"] for c in found] == ["one", "two"]
    assert len(seen) == 2
    assert query_of(seen[1])["pageToken"] == "page-2"


def test_hidden_calendars_are_askable_in_the_first_place():
    """If the list request filtered them out server-side we could not tell hidden from
    absent, and the skip above would be guesswork."""
    cal, seen = session([events([calendar()])])
    cal.calendars()
    assert query_of(seen[0])["showHidden"] == "true"


# ------------------------------------------------------------------ the window


def test_the_window_is_asked_for_expanded_and_with_cancellations():
    cal, seen = session([events([])])
    cal.events("steve@example.com", START, END)
    sent = query_of(seen[0])

    assert sent["timeMin"] == "2026-09-21T07:00:00Z"
    # seven days back plus sixty forward: the engine's window, unchanged for Google
    assert sent["timeMax"] == "2026-11-27T07:00:00Z"
    assert sent["singleEvents"] == "true"      # occurrences, not series
    assert sent["orderBy"] == "startTime"
    assert sent["showDeleted"] == "true"       # so a cancellation reads as one
    assert sent["maxResults"] == str(gc.PAGE_SIZE)


def test_the_window_comes_back_as_rows_the_engine_already_knows():
    cal, _ = session([events([
        {"id": "e1", "summary": "Dentist", "status": "confirmed",
         "start": {"dateTime": "2026-09-21T09:00:00-07:00"},
         "end": {"dateTime": "2026-09-21T10:00:00-07:00"}},
    ])])
    rows, cancelled = cal.events("steve@example.com", START, END)
    assert cancelled == []
    assert rows[0]["calendar_ref"] == "steve@example.com"
    assert rows[0]["provider"] == "google"
    assert rows[0]["start_utc"] == "2026-09-21T16:00:00+00:00"


def test_the_window_is_assembled_across_pages():
    cal, seen = session([
        events([{"id": "a", "start": {"date": "2026-09-21"}, "end": {"date": "2026-09-22"}}],
               nextPageToken="more"),
        events([{"id": "b", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}}]),
    ])
    rows, _ = cal.events("steve@example.com", START, END)
    assert [row["uid"] for row in rows] == ["a", "b"]
    assert query_of(seen[1])["pageToken"] == "more"


def test_the_calendar_id_survives_being_put_in_a_path():
    cal, seen = session([events([])])
    cal.events("family_123@group.calendar.google.com", START, END)
    assert unquote(seen[0].url.path).endswith("/calendars/family_123@group.calendar.google.com/events")


def test_the_access_token_is_read_for_every_request():
    """The engine builds one session per sync and may refresh mid-flight; a header frozen
    at construction would keep using the token that just expired."""
    cal, seen = session([events([]), events([])])
    cal.events("a", START, END)
    cal.calendars()
    assert seen[0].headers["Authorization"] == "Bearer at-1"
    assert seen[1].headers["Authorization"] == "Bearer at-2"


# ------------------------------------------------------------------ refusals


def test_a_refused_token_is_a_reconnect():
    cal, _ = session([{"error": {"code": 401, "message": "Invalid Credentials"}}], status=401)
    with pytest.raises(gc.Reconnect) as caught:
        cal.calendars()
    assert "again" in str(caught.value)


def test_a_disabled_api_names_the_click_that_fixes_it():
    """The commonest first-run failure by a distance, and the raw message does not say
    where to go."""
    body = {"error": {"code": 403, "message": "Google Calendar API has not been used in "
                                              "project 12345 before or it is disabled."}}
    cal, _ = session([body], status=403)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    message = str(caught.value)
    assert "has not been used in project" in message
    assert "Library" in message


def test_a_forbidden_scope_is_reported_as_itself():
    cal, _ = session([{"error": {"code": 403, "message": "Request had insufficient authentication scopes."}}],
                     status=403)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "insufficient authentication scopes" in str(caught.value)


def test_a_calendar_that_vanished_says_so():
    cal, _ = session([{"error": {"code": 404, "message": "Not Found"}}], status=404)
    with pytest.raises(gc.CalendarError) as caught:
        cal.events("gone@example.com", START, END)
    assert "does not know that calendar" in str(caught.value)


def test_rate_limiting_is_reported_as_temporary():
    cal, _ = session([{"error": {"code": 429, "message": "Rate Limit Exceeded"}}], status=429)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "rate-limiting" in str(caught.value)


def test_a_server_error_is_a_sentence():
    cal, _ = session([{"error": {"code": 500, "message": "Backend Error"}}], status=500)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "500" in str(caught.value) and "Backend Error" in str(caught.value)


def test_no_credential_ever_reaches_an_error_message():
    """A server that quotes your request back at you is not unusual, and this message is
    stored in the database and shown in the rail."""
    body = {"error": {"code": 500, "message": "rejected Authorization: Bearer at-1 for calendar a"}}
    cal, _ = session([body], status=500)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "at-1" not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_a_runaway_page_loop_is_stopped():
    """A page token that never ends costs a request per page forever."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=events([calendar()], nextPageToken="always-more"))

    cal = gc.GoogleCalendar(FakeAuth(), transport=httpx.MockTransport(handler))
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert str(gc.MAX_PAGES) in str(caught.value)


def test_an_answer_that_is_not_json_is_reported_as_such():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>nope</html>"))
    cal = gc.GoogleCalendar(FakeAuth(), transport=transport)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "JSON" in str(caught.value)


def test_a_timeout_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    cal = gc.GoogleCalendar(FakeAuth(), transport=httpx.MockTransport(handler))
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "did not answer in time" in str(caught.value)


def test_a_body_larger_than_we_parse_is_refused():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=b" " * (gc.MAX_BYTES + 1),
                                 headers={"Content-Type": "application/json"})
    )
    cal = gc.GoogleCalendar(FakeAuth(), transport=transport)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()
    assert "8 MB" in str(caught.value)


def test_a_google_error_body_cannot_carry_the_token_into_a_log():
    """Google quotes the request back inside its errors, Authorization header included, and
    whatever comes out of here is written to sync_log and read by the rail. The fake auth
    issues "at-1" on the first call, so that is the token this body leaks."""
    body = {"error": {"code": 500, "message": "Backend Error",
                      "detail": "GET /calendar/v3/users/me/calendarList failed, "
                                "Authorization: Bearer at-1"}}
    cal, _ = session([body], status=500)
    with pytest.raises(gc.CalendarError) as caught:
        cal.calendars()

    message = str(caught.value)
    assert "at-1" not in message, message
    assert "Backend Error" in message, "it still has to say what happened"
