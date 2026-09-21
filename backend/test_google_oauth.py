"""Google's OAuth, against scripted replies.

No network and no Google account: every exchange here is driven through an httpx transport
that answers with the documents Google sends, and refuses on demand. The point of the scripted replies is the failure paths — a weekly revocation, a
server echoing back what it was sent, a token endpoint that answers HTML — which are the
ones that cannot be reproduced against the real thing at will.
"""

from __future__ import annotations

import json
import os
import stat
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import google_oauth as g

SECRET = "GOCSPX-not-a-real-secret"
REFRESH = "1//not-a-real-refresh-token"


@pytest.fixture(autouse=True)
def clean_cache():
    """The token cache is per-process by design; between tests it is a leak."""
    g.forget_cached_tokens()
    yield
    g.forget_cached_tokens()


def write_env(tmp_path, body: str):
    path = tmp_path / "google.env"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = f"GOOGLE_CLIENT_ID=1234.apps.googleusercontent.com\nGOOGLE_CLIENT_SECRET={SECRET}\n"


def configuration(**overrides) -> g.Configuration:
    base = dict(client_id="1234.apps.googleusercontent.com", client_secret=SECRET)
    base.update(overrides)
    return g.Configuration(**base)


def scripted(handler):
    """(transport, requests) — every request the module makes, and what it got back."""
    seen: list[httpx.Request] = []

    def wrapper(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapper), seen


def form_of(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


# ------------------------------------------------------------------ the consent screen


def test_the_consent_url_asks_for_read_only_and_a_refresh_token():
    """The scope is the promise. Asking for the write scope as well would keep every other
    sentence in the README while breaking the one that matters."""
    url = g.authorize_url(
        configuration(), redirect_uri="https://sundial.example/oauth/google/callback",
        state="state-abc", challenge="challenge-xyz",
    )
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    assert url.startswith(g.AUTH_ENDPOINT)
    scopes = query["scope"].split()
    assert "https://www.googleapis.com/auth/calendar.readonly" in scopes
    assert "https://www.googleapis.com/auth/calendar" not in scopes
    assert not [s for s in scopes if s.endswith("/auth/calendar.events")]

    assert query["access_type"] == "offline"      # what asks for a refresh token
    assert query["prompt"] == "consent"           # what asks for one a second time
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == "challenge-xyz"
    assert query["state"] == "state-abc"
    assert query["redirect_uri"] == "https://sundial.example/oauth/google/callback"
    assert query["client_id"] == "1234.apps.googleusercontent.com"


def test_pkce_challenge_is_the_sha256_of_the_verifier():
    import base64
    import hashlib

    verifier, challenge = g.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    assert challenge == expected.rstrip("=")
    assert challenge != verifier
    assert len(verifier) >= 43  # RFC 7636's floor


def test_two_handshakes_do_not_share_a_verifier():
    first = g.Pending().start("https://sundial.example/cb")
    second = g.Pending().start("https://sundial.example/cb")
    assert first.state != second.state
    assert first.verifier != second.verifier


def test_a_handshake_can_only_be_claimed_once():
    pending = g.Pending()
    started = pending.start("https://sundial.example/cb")

    claimed = pending.claim(started.state)
    assert claimed.verifier == started.verifier

    with pytest.raises(g.CalendarError) as caught:
        pending.claim(started.state)
    assert "already been used" in str(caught.value) or "not one we started" in str(caught.value)


def test_an_unknown_state_is_refused():
    with pytest.raises(g.CalendarError):
        g.Pending().claim("something-we-invented")


def test_a_handshake_left_open_is_forgotten():
    clock = [1000.0]
    pending = g.Pending(ttl=600, now=lambda: clock[0])
    started = pending.start("https://sundial.example/cb")
    clock[0] += 601
    with pytest.raises(g.CalendarError):
        pending.claim(started.state)
    assert len(pending) == 0


# ------------------------------------------------------------------ exchanging the code


def test_the_exchange_sends_what_google_requires():
    def handler(request):
        assert request.url == g.TOKEN_ENDPOINT
        return httpx.Response(200, json={"access_token": "at-1", "refresh_token": REFRESH,
                                         "expires_in": 3599})

    transport, seen = scripted(handler)
    tokens = g.exchange(
        configuration(), code="the-code", verifier="the-verifier",
        redirect_uri="https://sundial.example/cb", transport=transport, now=lambda: 5000.0,
    )

    sent = form_of(seen[0])
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["code_verifier"] == "the-verifier"      # PKCE travels here, once
    assert sent["redirect_uri"] == "https://sundial.example/cb"
    assert sent["client_id"] == "1234.apps.googleusercontent.com"
    assert sent["client_secret"] == SECRET

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == REFRESH
    assert tokens.expires_at == 5000.0 + 3599


def test_a_connection_with_no_refresh_token_is_refused_rather_than_half_made():
    """An access token alone works for an hour and cannot be renewed, so it would look
    connected and stop working with nothing to point at."""
    transport, _ = scripted(lambda r: httpx.Response(200, json={"access_token": "at", "expires_in": 60}))
    with pytest.raises(g.CalendarError) as caught:
        g.exchange(configuration(), code="c", verifier="v", redirect_uri="https://x/cb",
                   transport=transport, now=lambda: 0.0)
    assert "refresh token" in str(caught.value)
    assert "permissions" in str(caught.value)


# ------------------------------------------------------------------ refreshing


def test_an_access_token_is_reused_until_it_is_nearly_expired():
    calls = []

    def handler(request):
        calls.append(form_of(request))
        return httpx.Response(200, json={"access_token": f"at-{len(calls)}", "expires_in": 3600})

    transport, _ = scripted(handler)
    clock = [1000.0]
    auth = g.GoogleAuth(configuration(refresh_token=REFRESH), transport=transport, now=lambda: clock[0])

    assert auth.token() == "at-1"
    clock[0] += 60
    assert auth.token() == "at-1"        # still good: no second round trip
    assert len(calls) == 1

    clock[0] += 3600 - 60                # inside the early window
    assert auth.token() == "at-2"
    assert len(calls) == 2
    assert calls[1]["grant_type"] == "refresh_token"
    assert calls[1]["refresh_token"] == REFRESH


def test_reconnecting_refreshes_immediately_rather_than_reusing_the_old_token():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": f"at-{len(calls)}", "expires_in": 3600})

    transport, _ = scripted(handler)
    g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    # A second refresh token means a second account or a reconnect: never the old token.
    tokens = g.refresh_tokens(configuration(), refresh_token="1//another", transport=transport,
                              now=lambda: 0.0)
    assert tokens.access_token == "at-2"
    assert len(calls) == 2


def test_the_headers_carry_the_token_and_nothing_else():
    transport, _ = scripted(lambda r: httpx.Response(200, json={"access_token": "at-9", "expires_in": 900}))
    auth = g.GoogleAuth(configuration(refresh_token=REFRESH), transport=transport, now=lambda: 0.0)
    assert auth.headers() == {"Authorization": "Bearer at-9"}


def test_an_unconnected_configuration_cannot_mint_a_token():
    with pytest.raises(g.NotConfigured) as caught:
        g.GoogleAuth(configuration())
    assert "not connected" in str(caught.value)


# ------------------------------------------------------------------ the 7-day trap


def test_the_weekly_revocation_is_reported_as_what_it_is():
    """Refresh tokens from an app in Google's Testing status are revoked after exactly
    seven days. It arrives as `invalid_grant`, which on its own reads like a bug."""
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant",
                                         "error_description": "Token has been expired or revoked."})

    transport, _ = scripted(handler)
    with pytest.raises(g.Reconnect) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)

    message = str(caught.value)
    assert "seven days" in message
    assert "Testing" in message
    assert "Publish app" in message       # the actual fix, in the message
    assert REFRESH not in message
    assert SECRET not in message


def test_a_refused_credential_is_a_reconnect_not_a_mystery():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})

    transport, _ = scripted(handler)
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert "401" in str(caught.value)
    assert "Invalid Credentials" in str(caught.value)


def test_a_server_error_is_a_sentence_rather_than_a_traceback():
    transport, _ = scripted(lambda r: httpx.Response(503, text="<html>upstream</html>"))
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert "503" in str(caught.value)


def test_an_answer_that_is_not_json_is_reported_as_such():
    transport, _ = scripted(lambda r: httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert "JSON" in str(caught.value)


# ------------------------------------------------------------------ what the errors say


def test_no_credential_ever_reaches_an_error_message():
    """Every failure path this module can take, and the one thing none of the messages may
    contain. A token in an error is a token in the database, a log file and a screenshot."""
    def refusing(status, body):
        return scripted(lambda r: httpx.Response(status, json=body))[0]

    bodies = [
        {"error": "invalid_grant", "error_description": REFRESH},
        {"error": {"code": 403, "message": f"API key not valid: {SECRET}"}},
        {"error": f"something about {REFRESH} and {SECRET}"},
    ]
    for body in bodies:
        for status in (400, 401, 403, 500):
            with pytest.raises(g.CalendarError) as caught:  # noqa: PT011 - the family, not one class
                g.refresh_tokens(configuration(), refresh_token=REFRESH,
                                 transport=refusing(status, body), now=lambda: 0.0)
            message = str(caught.value)
            assert REFRESH not in message
            assert SECRET not in message


def test_a_long_answer_is_cut_down_rather_than_parroted():
    """`message` comes from Google, but "print whatever the server said" is how a request
    ends up in an error message, so it is bounded."""
    transport, _ = scripted(lambda r: httpx.Response(500, json={"error": {"code": 500, "message": "x" * 5000}}))
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert len(str(caught.value)) < 400


def test_a_network_failure_is_a_sentence():
    def handler(request):
        raise httpx.ConnectError("nodename nor servname provided")

    transport, _ = scripted(handler)
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert "could not reach accounts.google.com" in str(caught.value)
    assert "ConnectError" in str(caught.value)


def test_a_timeout_says_so():
    def handler(request):
        raise httpx.TimeoutException("too slow")

    transport, _ = scripted(handler)
    with pytest.raises(g.CalendarError) as caught:
        g.refresh_tokens(configuration(), refresh_token=REFRESH, transport=transport, now=lambda: 0.0)
    assert "did not answer in time" in str(caught.value)


# ------------------------------------------------------------------ the account label


def test_the_account_label_comes_from_the_id_token():
    def b64(payload: dict) -> str:
        import base64

        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    id_token = f"{b64({'alg': 'RS256'})}.{b64({'email': 'steven@example.com'})}.signature"
    assert g.account_from_id_token(id_token) == "steven@example.com"


@pytest.mark.parametrize("broken", ["", "not-a-jwt", "a.b", "a.!!!.c", "a.eyJ9.c"])
def test_a_malformed_id_token_is_not_an_error(broken):
    """It is a label on a connection. Nothing downstream may fail because of it."""
    assert isinstance(g.account_from_id_token(broken), str)


# ------------------------------------------------------------------ the file


def test_a_missing_file_is_the_normal_not_configured_state(tmp_path):
    with pytest.raises(g.NotConfigured) as caught:
        g.load_configuration(tmp_path / "nothing-here.env")
    assert "GOOGLE_CLIENT_ID" in str(caught.value)


@pytest.mark.parametrize("body", ["", "GOOGLE_CLIENT_ID=\nGOOGLE_CLIENT_SECRET=\n", f"broken{SECRET}\n"])
def test_a_broken_file_names_the_key_and_never_the_value(tmp_path, body):
    try:
        g.load_configuration(write_env(tmp_path, body))
    except g.NotConfigured as exc:
        assert SECRET not in str(exc)
    else:
        pytest.fail("that file should not have loaded")


def test_the_file_is_read_back_whole(tmp_path):
    path = write_env(tmp_path, GOOD + f"GOOGLE_REFRESH_TOKEN={REFRESH}\nGOOGLE_ACCOUNT=a@b.c\n"
                                       "GOOGLE_REDIRECT_URI=https://sundial.example/cb\n")
    config = g.load_configuration(path)
    assert config.connected
    assert config.refresh_token == REFRESH
    assert config.account == "a@b.c"
    assert config.redirect_uri == "https://sundial.example/cb"


def test_the_redirect_must_be_https_or_local(tmp_path):
    with pytest.raises(g.CalendarError) as caught:
        g.load_configuration(write_env(tmp_path, GOOD + "GOOGLE_REDIRECT_URI=http://sundial.example/cb\n"))
    assert "https" in str(caught.value)
    # ...except to this box, where the code never reaches the wire.
    local = g.load_configuration(
        write_env(tmp_path, GOOD + "GOOGLE_REDIRECT_URI=http://127.0.0.1:8123/cb\n")
    )
    assert local.redirect_uri == "http://127.0.0.1:8123/cb"


def test_saving_a_token_keeps_the_client_secret_and_locks_the_file(tmp_path):
    path = write_env(tmp_path, GOOD)
    g.save(path, GOOGLE_REFRESH_TOKEN=REFRESH, GOOGLE_ACCOUNT="steven@example.com")

    text = path.read_text(encoding="utf-8")
    assert SECRET in text and REFRESH in text and "steven@example.com" in text
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"the config file is {oct(mode)}: it holds a client secret"

    config = g.load_configuration(path)
    assert config.connected and config.client_id.endswith("apps.googleusercontent.com")


def test_saving_twice_does_not_duplicate_keys(tmp_path):
    path = write_env(tmp_path, GOOD)
    for _ in range(3):
        g.save(path, GOOGLE_REFRESH_TOKEN=REFRESH)
    text = path.read_text(encoding="utf-8")
    assert text.count("GOOGLE_REFRESH_TOKEN") == 1
    assert text.count("GOOGLE_CLIENT_ID") == 1


def test_saving_leaves_no_temporary_file_behind(tmp_path):
    path = write_env(tmp_path, GOOD)
    g.save(path, GOOGLE_REFRESH_TOKEN=REFRESH)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "google.env"]
    assert leftovers == []


def test_saving_over_a_missing_file_creates_it_with_the_right_mode(tmp_path):
    path = tmp_path / "made" / "google.env"
    g.save(path, GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET=SECRET)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert g.load_configuration(path).client_secret == SECRET
