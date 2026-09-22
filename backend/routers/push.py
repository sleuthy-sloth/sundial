"""Subscriptions, and the one send that can be asked for on purpose.

One notification at the hour a block begins, and nothing else. The endpoint is a URL with
slashes and a query string in it, which is why turning one off is a POST with the endpoint
in the body rather than a DELETE with it in the path. What actually sends is `push.py`, and
the tick that does it on the hour is `main.py`'s.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import push
from schemas.push import SubscribeIn, UnsubscribeIn
from store import db

router = APIRouter()


@router.get("/api/push/key")
def push_key() -> dict:
    """What a browser needs in order to subscribe, and how many already have.

    The count is here rather than in a status endpoint of its own because the settings panel
    has to be able to tell "you turned this on" from "you turned this on and it is gone" —
    a subscription the push service has forgotten is deleted by the sender, and the panel is
    the only place that becomes visible.
    """
    with db() as conn:
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"public_key": push.public_key(), "subscribers": subscribers}


@router.post("/api/push/subscribe", status_code=201)
def push_subscribe(body: SubscribeIn) -> dict:
    """Keep a browser's subscription. Re-subscribing updates rather than doubles."""
    try:
        sub = push.subscription(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    with db() as conn:
        push.remember(conn, sub)
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"endpoint": sub["endpoint"], "subscribers": subscribers}


@router.post("/api/push/unsubscribe")
def push_unsubscribe(body: UnsubscribeIn) -> dict:
    """Forget one subscription. Turning it off has to work from the device that turned it on.

    A POST rather than a DELETE with the endpoint in the path: an endpoint is a URL with
    slashes and a query string, and a path parameter that has to be escaped twice is a bug
    waiting for the one subscription whose endpoint contains something awkward.
    """
    with db() as conn:
        removed = push.forget(conn, body.endpoint)
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"removed": bool(removed), "subscribers": subscribers}


@router.post("/api/push/test")
def push_test() -> dict:
    """Send one notification now, so the path can be proved without waiting for an hour."""
    with db() as conn:
        return push.nudge(conn)
