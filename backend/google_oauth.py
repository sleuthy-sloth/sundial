"""Google's OAuth 2.0, for a server nobody can sit in front of.

iCloud needs two lines in a file because an app-specific password is a static secret.
Google has no such thing: it needs an authorization code, a consent screen in somebody's
browser, and then a refresh token that has to be kept somewhere safe and renewed quietly
for years. That is most of a slice on its own, which is why it lives in its own module.

Four decisions worth knowing before reading the code:

**Read-only, in the grant itself.** The scope asked for is `calendar.readonly`. Google's
CalDAV endpoint would have been less code — the transport already exists — but it only
accepts the full `calendar` scope, i.e. write access to every calendar in the account. For
an app whose whole promise is "your calendar comes in, nothing goes back out", holding a
write-capable token would be a promise kept in the UI and broken in the credential.

**PKCE, and a state nobody can guess.** The consent screen is reached from the user's phone
and comes back through their browser, so the handshake is the part of this system most
exposed to somebody else's page. Both halves are short-lived and single-use.

**The 7-day trap.** While an OAuth app sits in Google's "Testing" publishing status, Google
revokes its refresh tokens after exactly seven days. Nothing about that failure looks like a
configuration problem — it looks like "Google rejected us" once a week, forever. It is
caught explicitly and reported as what it is, with the fix, because the fix is a click in a
console the user will not otherwise open.

**Credentials are written, never echoed.** This module both reads and writes the config
file, so it is the one place where a token could leak into a log or an error message; there
is a test that walks every failure path looking for one. The file is 0600 and written by
rename, so a crash mid-write cannot leave a half-file with a client secret in it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlencode, urlparse

import httpx

import env_file

from calendar_errors import CalendarError, NotConfigured, Reconnect

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Read-only, plus just enough identity to show which account is connected.
SCOPE = "https://www.googleapis.com/auth/calendar.readonly openid email"

TIMEOUT = 20.0

# Refresh a minute early: a token that expires during the request that needed it is a
# failure that only appears under load.
EARLY_SECONDS = 60

# A consent screen left open in a browser tab for an hour is not a handshake in progress.
PENDING_TTL_SECONDS = 10 * 60

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "google.env"

# Keys this module owns. Everything else in the file is left exactly as it was found.
SECRET_KEYS = ("GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")


def config_path() -> Path:
    return Path(os.environ.get("SUNDIAL_GOOGLE_ENV", DEFAULT_CONFIG))


# --------------------------------------------------------------------------- the file


@dataclass(frozen=True)
class Configuration:
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None
    refresh_token: Optional[str] = None
    account: str = ""

    @property
    def connected(self) -> bool:
        return bool(self.refresh_token)


def _check_redirect(url: str) -> str:
    """An authorization code in a query string, over plain http, is a code on the wire."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return url
    raise CalendarError(
        "the Google redirect must be https — an authorization code sent over plain http "
        "is a code somebody else can use"
    )


def load_configuration(path: str | Path | None = None) -> Configuration:
    """Read KEY=value from the config file. Failures name the key, never the value: the
    line that is out of place is usually the one holding the secret, and an error message
    is the last place it should end up."""
    p = Path(path or config_path())
    if not p.is_file():
        raise NotConfigured(
            f"no Google credentials at {p} — create it with GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET from console.cloud.google.com"
        )

    values: dict[str, str] = {}
    for number, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise NotConfigured(f"{p.name} line {number} is not KEY=value")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not values.get(k)]
    if missing:
        raise NotConfigured(f"{p.name} is missing {', '.join(missing)}")

    redirect = values.get("GOOGLE_REDIRECT_URI") or None
    return Configuration(
        client_id=values["GOOGLE_CLIENT_ID"],
        client_secret=values["GOOGLE_CLIENT_SECRET"],
        redirect_uri=_check_redirect(redirect) if redirect else None,
        refresh_token=values.get("GOOGLE_REFRESH_TOKEN") or None,
        account=values.get("GOOGLE_ACCOUNT", ""),
    )


# The order keys are written in, and the note at the top of the file. Here rather than in the
# writer because they are what this file *is*; `credentials.py` refers to both.
ORDER = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_ACCOUNT",
)

HEADER = (
    "# Written by sundial. Holds a client secret and a refresh token: keep it 0600,",
    "# keep it out of the repository, and delete the app's access at",
    "# myaccount.google.com/permissions to revoke it.",
)


def save(path: str | Path | None, **updates: str) -> None:
    """Merge keys into the config file, 0600, written by rename.

    A merge rather than a rewrite: the file holds a client secret a person pasted in by hand,
    and the app adding a refresh token to it must not be a way to lose that.
    """
    env_file.write(
        path or config_path(),
        {key: value for key, value in updates.items() if value is not None},
        order=ORDER,
        header=HEADER,
    )


# --------------------------------------------------------------------------- the handshake


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def challenge_for(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge). The verifier never leaves this process except to the token
    endpoint; the challenge is what travels through the browser."""
    verifier = _b64(secrets.token_bytes(48))
    return verifier, challenge_for(verifier)


@dataclass(frozen=True)
class Authorization:
    state: str
    verifier: str
    redirect_uri: str
    started_at: float


class Pending:
    """Authorizations that have been started and not yet come back.

    In memory, single-use, and short-lived. A restart mid-flow means starting again, which
    costs one tap; persisting a half-finished OAuth handshake would outlive the reason it
    existed.
    """

    def __init__(self, *, ttl: int = PENDING_TTL_SECONDS, now=time.time) -> None:
        self._ttl = ttl
        self._now = now
        self._open: dict[str, Authorization] = {}

    def start(self, redirect_uri: str) -> Authorization:
        self._expire()
        verifier, _challenge = pkce_pair()
        pending = Authorization(
            state=_b64(secrets.token_bytes(24)),
            verifier=verifier,
            redirect_uri=redirect_uri,
            started_at=self._now(),
        )
        self._open[pending.state] = pending
        return pending

    def claim(self, state: str) -> Authorization:
        """Take the handshake for `state`, once. Unknown, reused and expired are the same
        answer: this is not an authorization we started."""
        self._expire()
        pending = self._open.pop(state or "", None)
        if pending is None:
            raise CalendarError(
                "that Google sign-in is not one we started, or it has already been used — "
                "start the connection again from the calendar panel"
            )
        return pending

    def _expire(self) -> None:
        cutoff = self._now() - self._ttl
        for state in [s for s, p in self._open.items() if p.started_at < cutoff]:
            del self._open[state]

    def __len__(self) -> int:
        return len(self._open)


def authorize_url(
    configuration: Configuration,
    *,
    redirect_uri: str,
    state: str,
    challenge: str,
) -> str:
    """The consent screen. `access_type=offline` is what asks for a refresh token, and
    `prompt=consent` is what asks for one *again* on a second connection — without it
    Google returns an access token and no way to renew it."""
    query = urlencode(
        {
            "client_id": configuration.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTH_ENDPOINT}?{query}"


# --------------------------------------------------------------------------- tokens


@dataclass(frozen=True)
class Tokens:
    access_token: str
    expires_at: float
    refresh_token: str = ""
    account: str = ""

    def fresh(self, *, now: float, early: int = EARLY_SECONDS) -> bool:
        return bool(self.access_token) and now < self.expires_at - early


def describe(response: httpx.Response, secrets: Sequence[str] = ()) -> str:
    """An honest sentence for a Google API refusal, with no credential in it.

    The body is parsed rather than echoed: it is Google's document, it can be large, and
    "print whatever the server said" is how a request — including its Authorization header,
    when a proxy writes one — ends up in an error message. Anything we sent that was
    sensitive is redacted from whatever comes back, because a server that quotes your
    request back at you is not unusual and an error message is the last place a secret
    should be discovered.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("status") or "")
        code = str(error.get("code") or response.status_code)
    else:
        message = str(payload.get("error_description") or error or "")
        code = str(response.status_code)
    message = message.strip()[:300]
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), "[redacted]")
    return f"Google answered {code}" + (f": {message}" if message else "")


# Form fields that must never survive into a message, even quoted back by the server.
SENSITIVE_FIELDS = ("client_secret", "refresh_token", "code", "code_verifier")


def _sensitive(data: dict) -> tuple[str, ...]:
    return tuple(str(data.get(k) or "") for k in SENSITIVE_FIELDS)


def _form(url: str, data: dict, *, transport, timeout: float = TIMEOUT) -> dict:
    try:
        with httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "sundial (+self-hosted day planner)"},
        ) as client:
            response = client.post(url, data=data)
    except httpx.TimeoutException:
        raise CalendarError("accounts.google.com did not answer in time") from None
    except httpx.HTTPError as exc:
        raise CalendarError(f"could not reach accounts.google.com ({type(exc).__name__})") from None

    if response.status_code >= 400:
        payload = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if str(payload.get("error")) == "invalid_grant":
            raise Reconnect(
                "Google no longer accepts this authorization. The usual cause is an OAuth "
                "app still in Testing: Google revokes those refresh tokens after seven days. "
                "Publish it (console.cloud.google.com → APIs & Services → OAuth consent "
                "screen → Publish app) and connect again."
            )
        raise CalendarError(describe(response, _sensitive(data)))
    try:
        return response.json()
    except ValueError:
        raise CalendarError("the Google token endpoint did not answer with JSON") from None


def account_from_id_token(id_token: str) -> str:
    """The email in the id_token, for a label on the connection.

    Read, not verified, and deliberately only ever used for display: the token arrived
    directly from Google's token endpoint over TLS in the response to our own request, so
    it is not the untrusted-input case that a signature check protects against. Nothing in
    this app makes a decision based on it.
    """
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return ""
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return str(claims.get("email") or "")
    except Exception:  # noqa: BLE001 — a label is never worth failing a connection over
        return ""


def _tokens_from(payload: dict, *, now: float, fallback_refresh: str = "") -> Tokens:
    expires_in = payload.get("expires_in") or 3600
    try:
        expires_in = float(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600.0
    return Tokens(
        access_token=str(payload.get("access_token") or ""),
        expires_at=now + expires_in,
        refresh_token=str(payload.get("refresh_token") or "") or fallback_refresh,
        account=account_from_id_token(str(payload.get("id_token") or "")),
    )


def exchange(
    configuration: Configuration,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    transport: Optional[httpx.BaseTransport] = None,
    now=time.time,
) -> Tokens:
    """Trade the authorization code for tokens. The verifier is what proves this is the
    same process that started the handshake."""
    payload = _form(
        TOKEN_ENDPOINT,
        {
            "code": code,
            "code_verifier": verifier,
            "client_id": configuration.client_id,
            "client_secret": configuration.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        transport=transport,
    )
    tokens = _tokens_from(payload, now=now())
    if not tokens.access_token or not tokens.refresh_token:
        # Without a refresh token the connection works until the first hour is up and then
        # cannot be renewed at all, which is worse than failing here where it can be said.
        raise CalendarError(
            "Google returned no refresh token. Remove sundial's access at "
            "myaccount.google.com/permissions and connect again."
        )
    return tokens


# One process, one user: a cache rather than a table of them. Keyed by the refresh token it
# belongs to, so reconnecting with a different account cannot reuse the old access token.
_CACHE: dict[str, Tokens] = {}


def forget_cached_tokens() -> None:
    _CACHE.clear()


def refresh_tokens(
    configuration: Configuration,
    *,
    refresh_token: str,
    transport: Optional[httpx.BaseTransport] = None,
    now=time.time,
    reuse_cache: bool = True,
) -> Tokens:
    cached = _CACHE.get(refresh_token)
    moment = now()
    if reuse_cache and cached is not None and cached.fresh(now=moment):
        return cached

    payload = _form(
        TOKEN_ENDPOINT,
        {
            "refresh_token": refresh_token,
            "client_id": configuration.client_id,
            "client_secret": configuration.client_secret,
            "grant_type": "refresh_token",
        },
        transport=transport,
    )
    tokens = _tokens_from(payload, now=moment, fallback_refresh=refresh_token)
    _CACHE[refresh_token] = tokens
    return tokens


class GoogleAuth:
    """Hands out an access token, refreshing only when the one it has is nearly expired."""

    def __init__(
        self,
        configuration: Configuration,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        now=time.time,
        reuse_cache: bool = True,
    ) -> None:
        if not configuration.refresh_token:
            raise NotConfigured("Google is not connected yet")
        self.configuration = configuration
        self._transport = transport
        self._now = now
        self._reuse_cache = reuse_cache

    def token(self) -> str:
        tokens = refresh_tokens(
            self.configuration,
            refresh_token=self.configuration.refresh_token or "",
            transport=self._transport,
            now=self._now,
            reuse_cache=self._reuse_cache,
        )
        return tokens.access_token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

