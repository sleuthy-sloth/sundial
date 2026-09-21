"""CalDAV: the read-only part of it, which is all an import needs.

Discovery, the calendar list, and the objects inside a time window. No database in here,
so the protocol logic can be tested against scripted HTTP responses without a server, and
the storage rules can be tested without a network.

    PROPFIND  endpoint  (Depth 0)  current-user-principal     → who you are
    PROPFIND  principal (Depth 0)  calendar-home-set          → where your calendars are
    PROPFIND  home      (Depth 1)  resourcetype, displayname,
                                   ctag, colour, privileges   → which ones are calendars
    REPORT    calendar             calendar-query + time-range → the objects themselves

Everything Apple-specific is confined to a default endpoint, one namespace and a colour
format; point ICLOUD_CALDAV_URL at Fastmail or a Nextcloud box and the same code reads it.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

import calendar_sync as cs

DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
CALENDARSERVER = "http://calendarserver.org/ns/"
APPLE = "http://apple.com/ns/ical/"

DEFAULT_ENDPOINT = "https://caldav.icloud.com/"
TIMEOUT = 20.0
# A calendar server that has decided to send a gigabyte is a server having a bad day. This
# is not a memory guard — the body is already read by the time it is checked — it is a
# refusal to parse nonsense any further than this.
MAX_BYTES = 8 * 1024 * 1024

# The eight palette names with the edge colour each is drawn in, light theme, from
# styles.css (.c-<name>). A calendar arrives with its own colour from iCloud and has to
# land on one of these, because the palette is a validated app colour rather than a style
# choice. test_caldav.py asserts these still match the stylesheet.
PALETTE_RGB: dict[str, tuple[int, int, int]] = {
    "slate": (0x4E, 0x65, 0x77),
    "sky": (0x3F, 0x6B, 0x8A),
    "violet": (0x6A, 0x5A, 0x86),
    "amber": (0x96, 0x70, 0x2A),
    "emerald": (0x4A, 0x73, 0x58),
    "rose": (0x8D, 0x5A, 0x5A),
    "teal": (0x3F, 0x73, 0x73),
    "indigo": (0x4F, 0x56, 0x87),
}

PROVIDER = "icloud"

PRINCIPAL_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>"""

HOME_BODY = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="{CALDAV}"><d:prop><c:calendar-home-set/></d:prop></d:propfind>"""

CALENDARS_BODY = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="{CALDAV}" xmlns:cs="{CALENDARSERVER}" xmlns:a="{APPLE}">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <d:current-user-privilege-set/>
    <cs:getctag/>
    <d:sync-token/>
    <a:calendar-color/>
    <c:supported-calendar-component-set/>
  </d:prop>
</d:propfind>"""


class CalDavError(Exception):
    """Something a person can act on. Never carries the password: the messages raised here
    are stored as `calendars.last_error` and shown in the interface, and a credential that
    leaks into either is a credential in a log file."""


class NotConfigured(CalDavError):
    """No usable credentials yet. A normal state, not a failure."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    endpoint: str = DEFAULT_ENDPOINT


def _check_endpoint(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return url  # a server on this box, which is not on the wire
    raise CalDavError(
        "the calendar URL must be https — an app-specific password sent over plain http "
        "is just a password"
    )


def load_credentials(path: str | Path) -> Credentials:
    """Read KEY=value from the credentials file.

    Failures name the key, never the value: a file that is one line out of place is
    usually the line holding the password, and an error message is the last place it
    should end up.
    """
    p = Path(path)
    if not p.is_file():
        raise NotConfigured(f"no credentials file at {p}")
    values: dict[str, str] = {}
    for number, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise NotConfigured(f"{p.name} line {number} is not KEY=value")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    missing = [k for k in ("ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD") if not values.get(k)]
    if missing:
        raise NotConfigured(f"{p.name} is missing {', '.join(missing)}")

    return Credentials(
        username=values["ICLOUD_USERNAME"],
        password=values["ICLOUD_APP_PASSWORD"],
        endpoint=_check_endpoint(values.get("ICLOUD_CALDAV_URL") or DEFAULT_ENDPOINT),
    )


def _hex_to_rgb(value: str) -> Optional[tuple[int, int, int]]:
    text = value.strip().lstrip("#")
    if len(text) == 8:  # iCloud sends #RRGGBBAA
        text = text[:6]
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB to CIE Lab under a D65 white point. Twenty lines, no dependency."""

    def to_linear(channel: int) -> float:
        c = channel / 255
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = (to_linear(v) for v in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _colour_distance(rgb: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    """Hue first, then lightness — because that is how a colour is named.

    Three metrics were tried on Apple's red (#FF3B30) before this one. RGB distance picked
    amber; so did redmean; so did plain Euclidean distance in Lab, and each time it was
    defensible arithmetic and wrong to look at. Rose is a dark *desaturated* brick, so its
    numbers sit nearer a brown-gold than a vivid red does. Red's hue is 32 degrees and
    rose's is 25; amber's is 80. Hue is the thing the person picking a colour meant.
    """
    light, a1, b1 = _lab(rgb)
    other_light, a2, b2 = _lab(other)
    chroma, other_chroma = math.hypot(a1, b1), math.hypot(a2, b2)
    if min(chroma, other_chroma) < 6:
        # Almost grey: there is no hue to compare, so everything is far away and the
        # least colourful entry wins — which is what grey should do.
        return 100 + abs(light - other_light) + abs(chroma - other_chroma)
    turn = abs(math.atan2(b1, a1) - math.atan2(b2, a2))
    hue = math.degrees(min(turn, 2 * math.pi - turn))
    return hue + 0.25 * abs(light - other_light)


def nearest_colour(value: Optional[str]) -> str:
    """The palette name closest to a calendar's own colour.

    iCloud hands out any colour the user picked from a wheel; sundial has eight, and a
    ninth invented on the spot would not have a dark-theme pair or a contrast-checked
    edge. Nearest is honest: the calendar keeps its flavour, and the app keeps its palette.
    """
    rgb = _hex_to_rgb(value) if value else None
    if rgb is None:
        return "slate"
    return min(PALETTE_RGB, key=lambda name: _colour_distance(rgb, PALETTE_RGB[name]))


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _props(element: ET.Element) -> dict[str, ET.Element]:
    """Every child of a <d:prop>, keyed by local name.

    By local name rather than by prefix: prefixes are the server's business and iCloud,
    Fastmail and Nextcloud do not agree on them.
    """
    out: dict[str, ET.Element] = {}
    for child in element:
        out[_local(child.tag)] = child
    return out


def _text(element: Optional[ET.Element], default: str = "") -> str:
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _responses(root: ET.Element) -> list[tuple[str, dict[str, ET.Element]]]:
    """The <d:response> elements of a multistatus, as (href, props) pairs.

    A tuple rather than a dict keyed by string: an href and a bag of property elements
    are two different things, and typing them as one made every caller's fetch look like
    it might return a string.
    """
    out: list[tuple[str, dict[str, ET.Element]]] = []
    for response in root:
        if _local(response.tag) != "response":
            continue
        href = ""
        props: dict[str, ET.Element] = {}
        for child in response:
            name = _local(child.tag)
            if name == "href":
                href = _text(child)
            elif name == "propstat":
                for part in child:
                    if _local(part.tag) == "prop":
                        props.update(_props(part))
        out.append((href, props))
    return out


class CalDavClient:
    """One session against one server. Pass a transport to test it against scripted replies."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self.credentials = credentials
        self.origin = credentials.endpoint
        # Walked once: discovery is three round trips, and a sync was doing the first two
        # twice because home() asked who the account was all over again.
        self._principal: Optional[str] = None
        self._home: Optional[str] = None
        self._client = httpx.Client(
            auth=(credentials.username, credentials.password),
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "sundial (+self-hosted day planner)", "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CalDavClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- protocol

    def _request(
        self, method: str, url: str, body: str, depth: str, ok: tuple[int, ...] = (207, 200)
    ) -> ET.Element:
        target = urljoin(self.origin, url) if url.startswith("/") or "://" not in url else url
        try:
            response = self._client.request(
                method,
                target,
                content=body.encode("utf-8"),
                headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
            )
        except httpx.TimeoutException:
            raise CalDavError(f"{urlparse(target).hostname} did not answer in time") from None
        except httpx.HTTPError as exc:
            raise CalDavError(f"could not reach {urlparse(target).hostname} ({type(exc).__name__})") from None

        if response.status_code in (401, 403):
            raise CalDavError(
                f"{urlparse(target).hostname} refused those credentials "
                f"({response.status_code}). iCloud needs an app-specific password from "
                "appleid.apple.com — your normal Apple ID password will not work."
            )
        if response.status_code not in ok:
            path = urlparse(target).path.rstrip("/") or "/"
            raise CalDavError(f"{method} {path} answered {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise CalDavError(f"{method} {urlparse(target).path} returned more than 8 MB")

        try:
            return ET.fromstring(response.content)
        except ET.ParseError:
            raise CalDavError(f"{method} {urlparse(target).path} did not answer with XML") from None

    def principal(self) -> str:
        if self._principal:
            return self._principal
        root = self._request("PROPFIND", self.origin, PRINCIPAL_BODY, "0")
        for _href, props in _responses(root):
            found = props.get("current-user-principal")
            if found is not None:
                for child in found:
                    if _local(child.tag) == "href":
                        self._principal = _text(child)
                        return self._principal
        raise CalDavError("the server did not say who this account is")

    def home(self, principal: Optional[str] = None) -> str:
        if self._home and principal is None:
            return self._home
        root = self._request("PROPFIND", principal or self.principal(), HOME_BODY, "0")
        for _href, props in _responses(root):
            found = props.get("calendar-home-set")
            if found is not None:
                for child in found:
                    if _local(child.tag) == "href":
                        self._home = _text(child)
                        return self._home
        raise CalDavError("the server did not say where this account's calendars live")

    def calendars(self, home: Optional[str] = None) -> list[dict]:
        """Every collection that is actually a calendar of events."""
        home = home or self.home()
        root = self._request("PROPFIND", home, CALENDARS_BODY, "1")
        out: list[dict] = []
        for href, props in _responses(root):
            if not href or href.rstrip("/") == home.rstrip("/"):
                continue

            kinds = {_local(node.tag) for node in props.get("resourcetype", [])}
            if "calendar" not in kinds:
                continue  # the scheduling inbox is a collection, not a calendar

            supported = props.get("supported-calendar-component-set")
            if supported is not None:
                components = {node.get("name") for node in supported}
                if components and "VEVENT" not in components:
                    continue  # a reminders-only list, which has nothing to plan around

            privileges = props.get("current-user-privilege-set")
            writable = 1 if privileges is not None and any(
                _local(node.tag) == "write" for node in privileges.iter()
            ) else 0

            name = _text(props.get("displayname")) or href.rstrip("/").rpartition("/")[2] or "Calendar"
            out.append(
                {
                    "ref": href,
                    "provider": PROVIDER,
                    "name": name,
                    "colour": nearest_colour(_text(props.get("calendar-color")) or None),
                    "ctag": _text(props.get("getctag")) or _text(props.get("sync-token")) or None,
                    "writable": writable,
                }
            )
        return out

    def events(self, calendar_ref: str, start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
        """The objects in a window, already converted, with each row's ETag stamped on.

        The ETag lives in the CalDAV response and not in the ICS, so it has to be joined
        back onto the rows here — that is the only reason this method knows about rows at
        all rather than handing back raw calendar data.
        """
        body = f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="{CALDAV}">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
    <c:time-range start="{_stamp(start)}" end="{_stamp(end)}"/>
  </c:comp-filter></c:comp-filter></c:filter>
</c:calendar-query>"""

        root = self._request("REPORT", calendar_ref, body, "1")
        rows: list[dict] = []
        cancelled: list[str] = []
        for href, props in _responses(root):
            ics = _text(props.get("calendar-data")) or ""
            if not ics:
                continue
            etag = _text(props.get("getetag")).strip('"') or None
            # calendar_ref is the *collection*: it is a foreign key into calendars.ref, and
            # the object's own href would violate it. The UID inside the ICS already
            # identifies the event within its calendar.
            parsed, gone = cs.events_from_ics(ics, calendar_ref, PROVIDER)
            for row in parsed:
                row["etag"] = etag
            rows.extend(parsed)
            cancelled.extend(gone)
        return rows, cancelled


def _stamp(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
