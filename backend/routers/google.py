"""Google's consent flow, which is built and not switched on.

Two routes that a browser arrives at rather than fetches, so they answer with HTML — which is
why they are not in `calendar.py` with the rest of the calendar's JSON. The scope asked for is
`calendar.readonly`: read-only in the grant itself, not only in this app's behaviour, so the
token cannot write to a calendar even if it is misused.
"""

from __future__ import annotations

import html
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import google_oauth
from caldav import NotConfigured
from calendar_errors import CalendarError

router = APIRouter()

PENDING = google_oauth.Pending()


def _google_configuration() -> Optional[google_oauth.Configuration]:
    try:
        return google_oauth.load_configuration(google_oauth.config_path())
    except NotConfigured:
        return None


def google_redirect(request: Request) -> str:
    """Where Google sends the browser back to.

    Taken from the request's own origin unless google.env names one, so the repository never
    has to contain a hostname — the same reasoning as VITE_APP_URL — and set explicitly only
    when something in front of the app rewrites Host.
    """
    configured = _google_configuration()
    if configured is not None and configured.redirect_uri:
        return configured.redirect_uri
    return str(request.base_url).rstrip("/") + "/oauth/google/callback"


def _page(title: str, body: str, *, ok: bool) -> HTMLResponse:
    """The one page in this app that is not the app.

    A browser arrives at these two routes rather than fetch(), so they answer with HTML. It
    matters more than usual here: Google refuses to render its consent screen inside an
    embedded webview, which is what the phone's client is, so the flow finishes in Safari
    and lands on this page rather than back inside the app.
    """
    accent = "#8A5A2B" if ok else "#8D5A5A"
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)} — sundial</title></head>"
        "<body style=\"background:#F4F1E8;color:#25231F;font:16px/1.6 system-ui,sans-serif;"
        "margin:0;padding:2.5rem 1.5rem\"><main style=\"max-width:32rem;margin:0 auto\">"
        f"<h1 style=\"font-size:.8rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;"
        f"color:{accent}\">{html.escape(title)}</h1>"
        f"<p>{body}</p>"
        f"<p><a href=\"/\" style=\"color:{accent}\">Back to sundial</a></p>"
        "</main></body></html>"
    )


@router.get("/oauth/google/start")
def google_start(request: Request):
    """Send the browser to Google's consent screen.

    The scope asked for is `calendar.readonly`: read-only in the grant itself, not only in
    this app's behaviour, so the token cannot write to a calendar even if it is misused.
    """
    configuration = _google_configuration()
    if configuration is None:
        raise HTTPException(400, "Google is not set up yet: create google.env with a client id "
                                 "and secret from console.cloud.google.com")
    redirect = google_redirect(request)
    pending = PENDING.start(redirect)
    return RedirectResponse(
        google_oauth.authorize_url(
            configuration,
            redirect_uri=redirect,
            state=pending.state,
            challenge=google_oauth.challenge_for(pending.verifier),
        ),
        status_code=302,
    )


@router.get("/oauth/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
) -> HTMLResponse:
    """Where Google sends the browser back to, with an authorization code.

    Every failure here is a page rather than a JSON error, because the thing looking at it is
    a person in a browser tab. None of them carry a credential: the code, the verifier and
    the tokens are never named in what is rendered.
    """
    if error:
        return _page("Google said no",
                     f"Google refused the connection: {html.escape(error)}.", ok=False)
    if not code:
        return _page("Nothing to connect",
                     "That address did not carry an authorization code.", ok=False)

    try:
        pending = PENDING.claim(state)
    except CalendarError as exc:
        return _page("That link has expired", html.escape(str(exc)), ok=False)

    configuration = _google_configuration()
    if configuration is None:
        return _page("Google is not set up",
                     "The credentials went missing between starting and finishing. "
                     "Check that google.env is still there.", ok=False)

    try:
        tokens = google_oauth.exchange(
            configuration,
            code=code,
            verifier=pending.verifier,
            redirect_uri=pending.redirect_uri,
        )
    except CalendarError as exc:
        return _page("Google refused", html.escape(str(exc)), ok=False)

    google_oauth.save(
        google_oauth.config_path(),
        GOOGLE_REFRESH_TOKEN=tokens.refresh_token,
        GOOGLE_ACCOUNT=tokens.account,
    )
    return _page(
        "Connected",
        "sundial can now read your Google calendars"
        + (f" ({html.escape(tokens.account)})" if tokens.account else "")
        + ", and nothing else — the permission it holds cannot change anything. Google is "
        "not switched on in the interface yet, so this is as far as it goes for now.",
        ok=True,
    )
