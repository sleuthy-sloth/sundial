"""Google Calendar over the REST API, read-only, wearing the CalDAV transport's interface.

**Why REST and not CalDAV.** Google still speaks CalDAV, so the tempting move was to point
the existing transport at `apidata.googleusercontent.com` with an OAuth token instead of a
password. It cannot be done honestly: Google's CalDAV endpoint only accepts the full
`calendar` scope, which is write access to every calendar in the account. This app's whole
promise is that your calendar comes in and nothing goes back out, and holding a
write-capable token would keep that promise in the interface and break it in the
credential. The REST API accepts `calendar.readonly`, so the grant itself is read-only.

    GET /users/me/calendarList                    → which calendars, and what colour
    GET /calendars/{id}/events?timeMin&timeMax…   → one window, occurrences expanded

The same three methods as `CalDavClient` — `calendars()`, `events()`, `close()` — so
`calendar_service` does not know or care which transport it is holding. Everything specific
to Google stops at this file and `google_oauth.py`, and everything fiddly about converting
an event is in `calendar_sync.events_from_google`, where it has no network to hide behind.

Two deliberate omissions, both about not building a clever thing that loses events:

* **No ctag.** A CalDAV calendar advertises a collection tag that changes when anything
  inside it changes, so a sync can skip the fetch entirely. Google's equivalent is an etag
  on the *calendarList entry*, and it does not move when events change — confirmed, and it
  is the kind of thing that would look like it worked. So Google calendars always fetch
  their window, and `ctag` stays None.
* **No syncToken.** Google's incremental cursor would fetch only what changed, which is
  faster and is exactly the hand-rolled cursor the calendar spec already refused: its
  failure mode is a silently missing event, and the window is small enough to just refetch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol
from urllib.parse import quote

import httpx

import calendar_sync as cs
from calendar_errors import CalendarError, Reconnect
from google_oauth import describe
from palette import nearest_colour

BASE = "https://www.googleapis.com/calendar/v3"
PROVIDER = "google"
TIMEOUT = 20.0

# Google's own maximum for one events page. Fewer round trips, and a window that fits in
# one page is one request per calendar per sync.
PAGE_SIZE = 2500

# A page token that never ends is a server having a bad day, not a person with 50,000
# events in one window. Same reasoning as MAX_BYTES in caldav.py.
MAX_PAGES = 20

MAX_BYTES = 8 * 1024 * 1024

# Roles that mean this account could write here. Kept because the column exists and the
# interface may want to say "read-only" one day; nothing in this slice writes anywhere.
WRITING_ROLES = ("owner", "writer")


class TokenSource(Protocol):
    """Whatever can hand over an Authorization header. GoogleAuth does; a test double
    does; nothing here needs the rest of it."""

    def headers(self) -> dict[str, str]: ...


def _stamp(when: datetime) -> str:
    """RFC 3339 in UTC. Google rejects a timeMin without an offset."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GoogleCalendar:
    """One session against one account. Pass a transport to test it against scripted JSON."""

    def __init__(
        self,
        auth: TokenSource,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self.auth = auth
        self.origin = BASE
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "sundial (+self-hosted day planner)", "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GoogleCalendar":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- transport

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """The Authorization header is built per request, not at construction: an access
        token that was refreshed during this sync has to be the one the next request uses."""
        try:
            headers = self.auth.headers()
        except CalendarError:
            raise
        url = f"{self.origin}{path}"
        try:
            response = self._client.get(url, params=params or {}, headers=headers)
        except httpx.TimeoutException:
            raise CalendarError("googleapis.com did not answer in time") from None
        except httpx.HTTPError as exc:
            raise CalendarError(f"could not reach googleapis.com ({type(exc).__name__})") from None

        token = headers.get("Authorization", "").removeprefix("Bearer ")
        if response.status_code == 401:
            raise Reconnect(
                "Google no longer accepts this authorization — connect Google again from "
                "the calendar panel."
            )
        if response.status_code == 403:
            message = describe(response, secrets=(token,))
            # A 403 is either a scope problem or the API never having been switched on, and
            # the second one is a click in a console, so say which it is.
            if "has not been used in project" in message or "it is disabled" in message:
                raise CalendarError(
                    f"{message} — enable the Google Calendar API for that project "
                    "(console.cloud.google.com → APIs & Services → Library)"
                )
            raise CalendarError(message)
        if response.status_code == 404:
            raise CalendarError("Google does not know that calendar any more")
        if response.status_code == 429:
            raise CalendarError("Google is rate-limiting this account; the next sync will try again")
        if response.status_code >= 400:
            raise CalendarError(describe(response, secrets=(token,)))
        if len(response.content) > MAX_BYTES:
            raise CalendarError(f"GET {path} returned more than 8 MB")

        try:
            return response.json()
        except ValueError:
            raise CalendarError(f"GET {path} did not answer with JSON") from None

    def _paged(self, path: str, params: dict) -> list[dict]:
        """Follow nextPageToken to the end, with a ceiling, and return every item."""
        items: list[dict] = []
        page_token: Optional[str] = None
        for _page in range(MAX_PAGES):
            query = dict(params)
            if page_token:
                query["pageToken"] = page_token
            payload = self._get(path, query)
            items.extend(payload.get("items") or [])
            page_token = payload.get("nextPageToken") or None
            if not page_token:
                return items
        raise CalendarError(
            f"Google kept returning pages for {path} after {MAX_PAGES} of them; stopping"
        )

    # ---------------------------------------------------------------- protocol

    def calendars(self) -> list[dict]:
        """Every calendar in the account's list that a person would recognise as theirs."""
        found: list[dict] = []
        for item in self._paged("/users/me/calendarList", {"maxResults": 250, "showHidden": "true"}):
            ref = str(item.get("id") or "")
            if not ref or item.get("deleted"):
                continue
            if item.get("hidden"):
                # They hid it in Google Calendar. Transcribing it into sundial would be
                # overruling a decision they already made, so it is skipped rather than
                # imported-and-disabled, which would look like sundial's own setting.
                continue
            found.append(
                {
                    "ref": ref,
                    "provider": PROVIDER,
                    "name": str(item.get("summaryOverride") or item.get("summary") or "").strip()
                    or "Calendar",
                    "colour": nearest_colour(str(item.get("backgroundColor") or "") or None),
                    # None on purpose: see the module docstring. A calendarList etag does not
                    # move when events change, so it cannot be a "skip the fetch" cursor.
                    "ctag": None,
                    "writable": 1 if str(item.get("accessRole") or "") in WRITING_ROLES else 0,
                }
            )
        return found

    def events(self, calendar_ref: str, start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
        """The window, with occurrences expanded by Google rather than by us.

        `singleEvents=true` is what makes a series arrive as one item per occurrence, which
        is the shape the storage already keeps for an instance — and `showDeleted=true` is
        what lets a whole event's cancellation be seen as a cancellation rather than as an
        unexplained absence.
        """
        params = {
            "timeMin": _stamp(start),
            "timeMax": _stamp(end),
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "true",
            "maxResults": PAGE_SIZE,
        }
        items = self._paged(f"/calendars/{quote(calendar_ref, safe='')}/events", params)
        return cs.events_from_google(items, calendar_ref, PROVIDER)
