"""The sending side of "a notification when a block starts".

`sw.js` has been able to receive one since it was written, and says so in a comment: a
notification arrives here once the sending side exists. This is that side.

Three pieces, deliberately separable, because the decisions in each have nothing to do with
the other two and each is testable on its own.

* **Who to tell** is a table of browser push subscriptions. A subscription is an endpoint URL
  plus the two keys a push service needs in order to read what we send it, so it is a secret
  in the same sense the calendar password is. It lives in the database rather than in a file
  because the app receives it from a browser, not from a person pasting it in. A subscription
  the push service has forgotten answers 404 or 410; that is not an error to report, it is a
  row to delete, and it is the only failure this module treats as routine.
* **What to say** is a title, a line and a tag. The tag is the block's id, so a second
  notification about the same block replaces the first instead of stacking under it. The
  words are chosen to survive the house rules: nothing here is allowed to sound urgent, and
  a block that started is not news about being late, it is news about what is starting.
* **When** is a tick. A block is due when its start has arrived, nobody has been told yet,
  and it started recently enough to still be worth saying. The lower bound is the load-bearing
  one: without it, starting the app after a weekend away would fire a notification for every
  block that had ever started.

There is no scheduler here, and that is the design rather than an omission. The app ticks
while it is running and is silent while it is not. A plan you are not running the app for is
a plan this app cannot tell you about — which is the honest behaviour for something that owns
one file in your home directory, and is why the phone-side check lives in the service worker
it already had.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush

import env_file
from store import db

# How late a tick may be and still say something. Ticks run every minute; this is the
# allowance for the app having been busy, asleep, or only just started. It is also what
# stops a notification from arriving so long after the hour that it reads as a reprimand.
GRACE_MIN = 10

# Long enough to reach a phone that is dozing, short enough that a notification about a
# block which is already half over never arrives at all. The push service drops anything
# older, which is the behaviour we want and is cheaper than deciding it here.
TTL_SECONDS = 300

ROOT = Path(__file__).resolve().parent

# Beside the calendar credentials. That is already the one directory this app keeps its
# must-not-commit files in, and a second directory to remember is a second directory to get
# wrong — the gitignore entry for it belongs in the same block as theirs.
DEFAULT_VAPID = ROOT.parent / "vapid.env"
DEFAULT_SUBJECT = "mailto:sundial@localhost"
VAPID_HEADER = (
    "# Written by sundial the first time something needed to be notified. This is the",
    "# identity a push service checks before it believes a notification came from this copy",
    "# of the app. Keep it 0600, and keep it out of the repository. Deleting it is a",
    "# supported repair: a new identity is made on the next visit, and each browser re-makes",
    "# its subscription against it, so the cost is one round trip and no lost plans.",
)


def vapid_path() -> Path:
    """Where the identity lives. Overridable so a test never touches the real one."""
    return Path(os.environ.get("SUNDIAL_VAPID_ENV", DEFAULT_VAPID))


def _public_key(vapid: Vapid02) -> str:
    """The public half as the browser wants it: an uncompressed point, base64url, unpadded."""
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_vapid(path: Optional[Path] = None) -> Vapid02:
    """The identity, made on first use and kept 0600 beside the calendar credentials.

    The key is stored base64-encoded because the file is one `KEY=value` per line and a PEM
    is not one line. A file that cannot be read back as a key is treated as no file at all:
    there is nothing to preserve, and refusing to start would strand the feature on a
    corrupt byte rather than on the one thing that fixes it.
    """
    target = path or vapid_path()
    stored = env_file.read(target).get("VAPID_PRIVATE_KEY", "")
    if stored:
        try:
            return Vapid02.from_pem(base64.b64decode(stored))
        except Exception:
            pass

    vapid = Vapid02()
    vapid.generate_keys()
    env_file.write(
        target,
        {"VAPID_PRIVATE_KEY": base64.b64encode(vapid.private_pem()).decode()},
        order=("VAPID_PRIVATE_KEY",),
        header=VAPID_HEADER,
    )
    return vapid


def public_key(path: Optional[Path] = None) -> str:
    """What the browser subscribes with. Makes the identity if this is the first ask."""
    return _public_key(load_vapid(path))


def subscription(body: Mapping[str, Any]) -> dict[str, str]:
    """One browser's subscription, or a ValueError naming what was wrong with it.

    Only the three fields a push service needs, taken from the shape the browser sends. The
    reply also carries `expirationTime` and sometimes a fourth key; keeping them would mean
    storing whatever a client felt like sending, in a row the sender then trusts.
    """
    keys = body.get("keys") or {}
    out = {
        "endpoint": str(body.get("endpoint") or "").strip(),
        "p256dh": str(keys.get("p256dh") or "").strip(),
        "auth": str(keys.get("auth") or "").strip(),
    }
    for name, value in out.items():
        if not value:
            raise ValueError(f"a subscription needs {name}")
        if "\n" in value:
            raise ValueError(f"{name} must be one line")
    if not out["endpoint"].startswith("https://"):
        raise ValueError("an endpoint must be https")
    return out


def remember(conn: Any, sub: Mapping[str, str], when: Optional[datetime] = None) -> None:
    """Keep this subscription. Re-subscribing the same browser updates rather than doubles."""
    conn.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
                VALUES (?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh,
                                               auth   = excluded.auth""",
        (sub["endpoint"], sub["p256dh"], sub["auth"], (when or datetime.now()).isoformat()),
    )


def forget(conn: Any, endpoint: str) -> int:
    """Drop one subscription. Returns how many rows went, which is 0 for an unknown one."""
    return conn.execute(
        "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
    ).rowcount


def spoken_time(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def spoken_length(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def payload(block: Mapping[str, Any]) -> dict[str, str]:
    """What the phone shows: the block's own words, then when and how long.

    No "starting now", no reminder number, no exclamation mark. It fires at the start by
    definition, so saying so would be repeating the only thing the notification already
    implies — and the house rules leave no room for a line that sounds like a hurry.
    """
    start = block.get("start_min")
    line = ""
    if start is not None:
        line = spoken_time(int(start))
        length = block.get("duration_min")
        if length:
            line = f"{line} · {spoken_length(int(length))}"
    return {
        "title": str(block.get("title") or "sundial"),
        "body": line,
        "tag": f"sundial-{block.get('id')}",
    }


def due(conn: Any, when: datetime) -> list[dict[str, Any]]:
    """Blocks that have started, that nobody has been told about, and that are still news.

    The anti-join is the whole of the "told" bookkeeping: a row in `push_sent` for this block
    on this day is the only state the sender keeps, so there is nothing to reset at midnight
    and nothing that can disagree with itself.
    """
    minute = when.hour * 60 + when.minute
    rows = conn.execute(
        """  SELECT b.id, b.title, b.start_min, b.duration_min
               FROM blocks b
          LEFT JOIN push_sent s ON s.block_id = b.id AND s.day = b.day
              WHERE b.day = ?
                AND b.start_min IS NOT NULL
                AND b.start_min <= ?
                AND b.start_min > ?
                AND s.block_id IS NULL
           ORDER BY b.start_min, b.id""",
        (when.date().isoformat(), minute, minute - GRACE_MIN),
    ).fetchall()
    return [dict(row) for row in rows]


def _deliver(
    subscriptions: Sequence[Any],
    body: str,
    key: Vapid02,
    claims: Mapping[str, str],
    pusher: Callable[..., Any],
) -> tuple[int, list[str], list[dict[str, str]]]:
    """Hand one body to every subscription. Returns how many took it, and the two failures.

    The three outcomes are kept apart on purpose, because they need different responses and
    collapsing any two of them is how a working subscription gets thrown away. A 404 or 410
    is the push service saying this subscription is over: routine, and the row goes. Anything
    else is a moment — the row is kept and the failure is reported, so the next tick tries it
    again rather than the person silently losing notifications.
    """
    accepted, expired, failed = 0, [], []
    for row in subscriptions:
        info = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            pusher(
                subscription_info=info,
                data=body,
                vapid_private_key=key,
                vapid_claims=claims,
                ttl=TTL_SECONDS,
            )
            accepted += 1
        except WebPushException as exc:
            if _status_of(exc) in (404, 410):
                expired.append(row["endpoint"])
            else:
                failed.append({"endpoint": row["endpoint"], "error": str(exc)[:200]})
        except Exception as exc:  # a transport error is not a subscription that ended
            failed.append({"endpoint": row["endpoint"], "error": str(exc)[:200]})
    return accepted, expired, failed


def _status_of(exc: WebPushException) -> Optional[int]:
    """The push service's answer, dug out of wherever pywebpush put it.

    A refused delivery arrives as an exception carrying the response, and the response is not
    always an attribute; older and newer versions differ. Both are checked so the one answer
    that matters — 404/410, this subscription is over — is never mistaken for a transient
    failure and retried until the grace window closes.
    """
    response = getattr(exc, "response", None) or (
        exc.args[1] if len(exc.args) > 1 else None
    )
    return getattr(response, "status_code", None)


def tick(
    conn: Any,
    when: Optional[datetime] = None,
    *,
    identity: Optional[Vapid02] = None,
    subject: Optional[str] = None,
    pusher: Callable[..., Any] = webpush,
) -> dict[str, Any]:
    """Say whatever has come due. Returns what happened, for the log and for the tests.

    `pusher` is injected so the whole tick runs against a recorder instead of a network. It
    is called with the same keyword arguments `pywebpush.webpush` takes, so a test double is
    a plain function and not a mock of a third-party library.

    A block is only recorded as said if at least one subscription accepted it. Otherwise a
    moment of network trouble would consume the notification rather than delay it.
    """
    when = when or datetime.now()
    expired: list[str] = []
    failed: list[dict[str, str]] = []

    subscriptions = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions ORDER BY created_at, endpoint"
    ).fetchall()
    blocks = due(conn, when)

    summary: dict[str, Any] = {
        "due": len(blocks),
        "sent": 0,
        "subscribers": len(subscriptions),
        "expired": expired,
        "failed": failed,
    }
    # Nobody to tell, or nothing to say. Either way nothing is recorded: a subscription added
    # this afternoon should not have had to be present this morning.
    if not blocks or not subscriptions:
        return summary

    key = identity or load_vapid()
    claims = {"sub": subject or os.environ.get("SUNDIAL_VAPID_SUBJECT", DEFAULT_SUBJECT)}

    for block in blocks:
        accepted, gone, bad = _deliver(subscriptions, json.dumps(payload(block)), key, claims, pusher)
        expired.extend(gone)
        failed.extend(bad)

        if accepted:
            conn.execute(
                "INSERT OR REPLACE INTO push_sent (block_id, day, sent_at) VALUES (?, ?, ?)",
                (block["id"], when.date().isoformat(), when.isoformat()),
            )
            summary["sent"] += 1

    for endpoint in set(expired):
        forget(conn, endpoint)
    return summary


def nudge(
    conn: Any,
    *,
    identity: Optional[Vapid02] = None,
    subject: Optional[str] = None,
    pusher: Callable[..., Any] = webpush,
) -> dict[str, Any]:
    """Send one notification to every subscriber now, whatever the clock says.

    Deliberately not a `tick`. This is about the subscription rather than about a block, so it
    matches nothing and records nothing: no `push_sent` row is written and the grace window
    does not apply. It exists so the path can be proved by pressing a button instead of
    waiting until nine o'clock, which is the only way to tell a broken subscription from a
    quiet morning.
    """
    subscriptions = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions ORDER BY created_at, endpoint"
    ).fetchall()
    if not subscriptions:
        return {"subscribers": 0, "sent": 0, "expired": [], "failed": []}

    key = identity or load_vapid()
    claims = {"sub": subject or os.environ.get("SUNDIAL_VAPID_SUBJECT", DEFAULT_SUBJECT)}
    body = json.dumps(
        {
            "title": "sundial",
            "body": "A notification, because you asked for one.",
            "tag": "sundial-test",
        }
    )
    accepted, expired, failed = _deliver(subscriptions, body, key, claims, pusher)
    for endpoint in set(expired):
        forget(conn, endpoint)
    return {
        "subscribers": len(subscriptions),
        "sent": accepted,
        "expired": expired,
        "failed": failed,
    }
