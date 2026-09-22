"""What a caller may send about notifications. Two bodies, and neither holds a secret.

The keys inside a subscription are the browser's, not this app's: it is handed them and keeps
them so the sender can sign with them. A VAPID private key never travels through a request body.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubscribeIn(BaseModel):
    """A browser's push subscription, exactly as `PushManager.subscribe` hands it over."""

    endpoint: str
    keys: dict[str, str] = Field(default_factory=dict)


class UnsubscribeIn(BaseModel):
    endpoint: str
