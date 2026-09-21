"""The transport, against scripted HTTP: the protocol in, rows out, and the messages it
produces when a server says no. No sockets, no real server, no credentials anywhere.

The XML here is shaped like what iCloud actually sends, prefixes and all, because the
parsing rules exist for those prefixes.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import caldav

STYLES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "styles.css"

SECRET = "abcd-efgh-ijkl-mnop"

PRINCIPAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
  <response>
    <href>/</href>
    <propstat>
      <prop><current-user-principal><href>/123456789/principal/</href></current-user-principal></prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>"""

HOME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/123456789/principal/</href>
    <propstat>
      <prop><C:calendar-home-set><href>/123456789/calendars/</href></C:calendar-home-set></prop>
      <status>HTTP/1.1 200 OK</status>
    </propstat>
  </response>
</multistatus>"""

CALENDARS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"
             xmlns:CS="http://calendarserver.org/ns/" xmlns:A="http://apple.com/ns/ical/">
  <response>
    <href>/123456789/calendars/</href>
    <propstat><prop><resourcetype><collection/></resourcetype></prop>
      <status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/home/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Home</displayname>
      <A:calendar-color>#3F6B8AFF</A:calendar-color>
      <CS:getctag>ctag-home-7</CS:getctag>
      <C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
      <current-user-privilege-set><privilege><read/></privilege><privilege><write/></privilege></current-user-privilege-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/work/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Work</displayname>
      <A:calendar-color>#FF0000FF</A:calendar-color>
      <sync-token>token-work-9</sync-token>
      <C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
      <current-user-privilege-set><privilege><read/></privilege></current-user-privilege-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/reminders/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Reminders</displayname>
      <C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/inbox/</href>
    <propstat><prop>
      <resourcetype><collection/><C:schedule-inbox/></resourcetype>
      <displayname>Inbox</displayname>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
</multistatus>"""

NO_NAME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/123456789/calendars/9a7b-4c/</href>
    <propstat><prop><resourcetype><collection/><C:calendar/></resourcetype></prop>
      <status>HTTP/1.1 200 OK</status></propstat>
  </response>
</multistatus>"""

EVENTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response>
    <href>/123456789/calendars/home/dentist.ics</href>
    <propstat><prop>
      <getetag>"etag-dentist-1"</getetag>
      <C:calendar-data>BEGIN:VCALENDAR&#13;
VERSION:2.0&#13;
BEGIN:VEVENT&#13;
UID:dentist-1&#13;
SUMMARY:Dentist&#13;
DTSTART;TZID=America/Los_Angeles:20260922T140000&#13;
DTEND;TZID=America/Los_Angeles:20260922T150000&#13;
LOCATION:123 Main St&#13;
END:VEVENT&#13;
END:VCALENDAR&#13;
</C:calendar-data>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/home/gone.ics</href>
    <propstat><prop>
      <getetag>"etag-gone-1"</getetag>
      <C:calendar-data>BEGIN:VCALENDAR&#13;
VERSION:2.0&#13;
BEGIN:VEVENT&#13;
UID:gone-1&#13;
SUMMARY:Cancelled thing&#13;
STATUS:CANCELLED&#13;
DTSTART:20260922T090000Z&#13;
DTEND:20260922T100000Z&#13;
END:VEVENT&#13;
END:VCALENDAR&#13;
</C:calendar-data>
    </prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
  <response>
    <href>/123456789/calendars/home/empty.ics</href>
    <propstat><prop><getetag>"etag-empty"</getetag></prop><status>HTTP/1.1 200 OK</status></propstat>
  </response>
</multistatus>"""


def credentials(endpoint="https://caldav.icloud.com/"):
    return caldav.Credentials(username="steven@example.com", password=SECRET, endpoint=endpoint)


def client(routes, endpoint="https://caldav.icloud.com/"):
    """A client whose every request is answered from `routes`, keyed by (method, path)."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = routes.get((request.method, request.url.path))
        if answer is None:
            return httpx.Response(404, text="no such route in this test")
        status, body = answer
        return httpx.Response(status, content=body.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    return caldav.CalDavClient(credentials(endpoint), transport=transport), seen


# ------------------------------------------------------------------- palette


def test_the_palette_matches_the_stylesheet():
    """nearest_colour is only honest while these two agree. A token change to an edge
    colour and a stale table here would quietly map calendars to the wrong swatch."""
    css = STYLES.read_text(encoding="utf-8")
    for name, rgb in caldav.PALETTE_RGB.items():
        found = re.search(rf"\.c-{name}\s+\{{[^}}]*--edge:\s*#([0-9a-fA-F]{{6}})", css)
        assert found, f"no light-theme edge for .c-{name} in styles.css"
        assert tuple(bytes.fromhex(found.group(1))) == rgb


def test_a_calendar_colour_lands_on_the_palette_name():
    assert caldav.nearest_colour("#3F6B8AFF") == "sky"      # iCloud's alpha suffix
    assert caldav.nearest_colour("#3F6B8A") == "sky"
    assert caldav.nearest_colour(" #4e6577 ") == "slate"


def test_every_palette_colour_is_its_own_nearest_neighbour():
    """The floor under the mapping: if this breaks, colours are being shifted by the
    rounding rather than matched."""
    for name, rgb in caldav.PALETTE_RGB.items():
        assert caldav.nearest_colour("#%02X%02X%02XFF" % rgb) == name


def test_apples_own_colours_land_on_something_recognisable():
    """What iCloud actually hands out. Apple red is the reason this is hue-first: three
    other metrics mapped it onto amber, which is the sort of detail that makes an imported
    calendar look broken. Blue lands on indigo rather than sky — indigo is the palette's
    bluest and sky is the steelier one, so a vivid azure really is nearer indigo."""
    for hex_value, expected in {
        "#FF3B30FF": "rose",     # red
        "#FF9500FF": "amber",    # orange
        "#FFCC00FF": "amber",    # yellow
        "#34C759FF": "emerald",  # green
        "#007AFFFF": "indigo",   # blue
        "#5856D6FF": "violet",   # indigo
        "#AF52DEFF": "violet",   # purple
        "#FF2D55FF": "rose",     # pink
        "#A2845EFF": "amber",    # brown
        "#8E8E93FF": "slate",    # grey — no hue to match, so the drabbest wins
    }.items():
        assert caldav.nearest_colour(hex_value) == expected, hex_value


def test_an_unusable_colour_falls_back_rather_than_failing():
    # A yellow with no near neighbour in the palette: something has to win, and a refused
    # import over a colour would be absurd.
    assert caldav.nearest_colour("#FFE100FF") in caldav.PALETTE_RGB
    assert caldav.nearest_colour(None) == "slate"
    assert caldav.nearest_colour("not a colour") == "slate"
    assert caldav.nearest_colour("#GGGGGG") == "slate"


# ------------------------------------------------------------------- credentials


def write_env(tmp_path, body):
    path = tmp_path / "icloud.env"
    path.write_text(body, encoding="utf-8")
    return path


def test_credentials_are_read_from_key_value_with_comments(tmp_path):
    path = write_env(
        tmp_path,
        f"# an app-specific password, not the Apple ID one\n\nICLOUD_USERNAME = steven@example.com\n"
        f"ICLOUD_APP_PASSWORD='{SECRET}'\nICLOUD_CALDAV_URL=https://caldav.icloud.com/\n",
    )
    creds = caldav.load_credentials(path)
    assert creds.username == "steven@example.com"
    assert creds.password == SECRET
    assert creds.endpoint == "https://caldav.icloud.com/"


def test_a_missing_file_is_a_normal_state_not_an_error(tmp_path):
    with pytest.raises(caldav.NotConfigured) as caught:
        caldav.load_credentials(tmp_path / "nothing-here.env")
    assert "nothing-here.env" in str(caught.value)


def test_a_missing_key_names_the_key_and_never_the_value(tmp_path):
    path = write_env(tmp_path, f"ICLOUD_USERNAME=steven@example.com\nICLOUD_APP_PASSWORD=\n")
    with pytest.raises(caldav.NotConfigured) as caught:
        caldav.load_credentials(path)
    assert "ICLOUD_APP_PASSWORD" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_a_malformed_line_reports_its_number_not_its_contents(tmp_path):
    """The line that is out of place is usually the password line."""
    path = write_env(tmp_path, f"ICLOUD_USERNAME=steven@example.com\nSECRET-{SECRET}\n")
    with pytest.raises(caldav.NotConfigured) as caught:
        caldav.load_credentials(path)
    assert "line 2" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_a_password_is_never_carried_in_an_error(tmp_path):
    """Every way this file can be wrong, and the one thing none of the messages say."""
    for body in ("", "ICLOUD_USERNAME=\nICLOUD_APP_PASSWORD=\n", f"broken{SECRET}\n"):
        path = write_env(tmp_path, body)
        try:
            caldav.load_credentials(path)
        except caldav.CalDavError as exc:
            assert SECRET not in str(exc)
        else:
            pytest.fail("that file should not have loaded")


def test_plain_http_is_refused_because_a_password_would_go_over_it():
    with pytest.raises(caldav.CalDavError) as caught:
        caldav._check_endpoint("http://caldav.example.com/")
    assert "https" in str(caught.value)
    # ...except to a server on this box, which never reaches the wire.
    assert caldav._check_endpoint("http://127.0.0.1:5232/") == "http://127.0.0.1:5232/"


# ------------------------------------------------------------------- discovery


DISCOVERY = {
    ("PROPFIND", "/"): (207, PRINCIPAL_XML),
    ("PROPFIND", "/123456789/principal/"): (207, HOME_XML),
    ("PROPFIND", "/123456789/calendars/"): (207, CALENDARS_XML),
}


def test_discovery_walks_principal_then_home():
    session, seen = client(DISCOVERY)
    assert session.principal() == "/123456789/principal/"
    assert session.home() == "/123456789/calendars/"
    # Two requests, not four: the principal and the home are walked once and remembered.
    assert [(r.method, r.url.path) for r in seen] == [
        ("PROPFIND", "/"),
        ("PROPFIND", "/123456789/principal/"),
    ]
    assert seen[0].headers["Depth"] == "0"
    assert b"current-user-principal" in seen[0].content
    assert b"calendar-home-set" in seen[1].content


def test_the_calendar_list_keeps_calendars_and_drops_other_collections():
    session, seen = client(DISCOVERY)
    found = session.calendars()
    assert [c["name"] for c in found] == ["Home", "Work"], "the inbox and reminders are not calendars"
    assert seen[2].headers["Depth"] == "1"


def test_a_calendar_carries_its_colour_ctag_and_privileges():
    session, _ = client(DISCOVERY)
    home, work = session.calendars()
    assert home["colour"] == "sky"           # #3F6B8A
    assert home["ctag"] == "ctag-home-7"
    assert home["writable"] == 1
    assert work["colour"] == "rose"          # pure red is rose, by hue
    assert work["ctag"] == "token-work-9", "no getctag, so the sync-token stands in"
    assert work["writable"] == 0
    assert home["ref"] == "/123456789/calendars/home/"


def test_a_calendar_with_no_name_falls_back_to_something_readable():
    routes = DISCOVERY | {("PROPFIND", "/123456789/calendars/"): (207, NO_NAME_XML)}
    session, _ = client(routes)
    assert session.calendars()[0]["name"] == "9a7b-4c"


# ------------------------------------------------------------------- events


def test_events_come_back_as_rows_with_the_etag_from_the_response():
    today = datetime(2026, 9, 22, 7, 0, tzinfo=timezone.utc)
    routes = {
        ("REPORT", "/123456789/calendars/home/"): (207, EVENTS_XML),
    }
    session, seen = client(routes)
    rows, cancelled = session.events(
        "/123456789/calendars/home/", today, datetime(2026, 11, 21, 7, 0, tzinfo=timezone.utc)
    )

    assert [r["title"] for r in rows] == ["Dentist"]
    assert rows[0]["etag"] == "etag-dentist-1", "the ETag lives in CalDAV, not in the ICS"
    # the collection, not the object: calendar_ref is a foreign key into calendars.ref
    assert rows[0]["calendar_ref"] == "/123456789/calendars/home/"
    assert rows[0]["uid"] == "dentist-1"
    assert rows[0]["start_utc"] == "2026-09-22T21:00:00+00:00"
    assert rows[0]["location"] == "123 Main St"
    assert cancelled == ["gone-1"], "a cancellation is an instruction to remove, not a row"

    body = seen[0].content.decode()
    assert "<c:time-range start=\"20260922T070000Z\" end=\"20261121T070000Z\"/>" in body
    assert "<d:getetag/>" in body and "<c:calendar-data/>" in body
    assert seen[0].headers["Depth"] == "1"


def test_a_calendar_with_no_events_is_an_empty_answer_not_an_error():
    routes = {("REPORT", "/123456789/calendars/home/"): (207, '<?xml version="1.0"?>\n<multistatus xmlns="DAV:"/>')}
    session, _ = client(routes)
    rows, cancelled = session.events("/123456789/calendars/home/", datetime.now(timezone.utc), datetime.now(timezone.utc))
    assert rows == [] and cancelled == []


# ------------------------------------------------------------------- refusals


def test_a_refused_password_produces_advice_not_a_stack_trace():
    routes = DISCOVERY | {("PROPFIND", "/"): (401, "")}
    session, _ = client(routes)
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    message = str(caught.value)
    assert "app-specific password" in message and "401" in message
    assert SECRET not in message


def test_a_server_error_names_the_path_and_nothing_else():
    routes = DISCOVERY | {("PROPFIND", "/123456789/calendars/"): (500, "")}
    session, _ = client(routes)
    with pytest.raises(caldav.CalDavError) as caught:
        session.calendars()
    assert "500" in str(caught.value) and "/123456789/calendars" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_a_timeout_is_reported_as_the_host_being_slow():
    def handler(request):
        raise httpx.ConnectTimeout("too slow")

    session = caldav.CalDavClient(credentials(), transport=httpx.MockTransport(handler))
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    assert "did not answer in time" in str(caught.value)


def test_an_unreachable_host_is_named_without_dumping_the_request():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    session = caldav.CalDavClient(credentials(), transport=httpx.MockTransport(handler))
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    message = str(caught.value)
    assert "caldav.icloud.com" in message and "ConnectError" in message
    assert SECRET not in message


def test_markup_that_is_not_xml_is_refused_cleanly():
    """A captive portal or a login page. Well-formed HTML would parse as XML and then fail
    later as "did not say who this account is" — this is the genuinely malformed case."""
    routes = {("PROPFIND", "/"): (207, "<html><body>a captive portal without an ending")}
    session, _ = client(routes)
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    assert "did not answer with XML" in str(caught.value)


def test_an_absurd_response_is_refused_rather_than_parsed():
    routes = {("PROPFIND", "/"): (207, "x" * (caldav.MAX_BYTES + 1))}
    session, _ = client(routes)
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    assert "more than 8 MB" in str(caught.value)


def test_a_server_that_says_nothing_about_the_account_is_an_error_not_an_infinite_loop():
    routes = {("PROPFIND", "/"): (207, '<?xml version="1.0"?>\n<multistatus xmlns="DAV:"/>')}
    session, _ = client(routes)
    with pytest.raises(caldav.CalDavError) as caught:
        session.principal()
    assert "did not say who" in str(caught.value)
