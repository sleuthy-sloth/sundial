"""The credentials a person may type into the app, and where each one goes.

One mechanism for both providers rather than a form per provider: the files are the same kind
of thing, and the rules that keep them safe are the same rules. What differs is the key names,
so those are a table.

This is the only place in sundial that accepts a secret from outside, so it is deliberately
small and hard to extend by accident:

* Keys come from the table. Anything else is refused rather than ignored — silently dropping a
  misspelled key means a file that looks right and does nothing.
* The refresh token is not in the table. Google's callback owns it, and a client that could
  post one could point sundial at somebody else's calendar.
* A value with a line break in it is refused. The file is one key per line, so a value that can
  contain a line break is not a value, it is a way to write keys nobody asked for.

Nothing here returns or logs a value it was given.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import env_file
import google_oauth
from calendar_service import config_path as icloud_config_path

# What the keys are called when the reply is a sentence for a person rather than a log line.
SPOKEN = {
    "ICLOUD_USERNAME": "an Apple ID",
    "ICLOUD_APP_PASSWORD": "an app-specific password",
    "ICLOUD_CALDAV_URL": "the server address",
    "GOOGLE_CLIENT_ID": "a Google client ID",
    "GOOGLE_CLIENT_SECRET": "a Google client secret",
    "GOOGLE_REDIRECT_URI": "the redirect address",
}

ICLOUD_HEADER = (
    "# Written by sundial. Holds an app-specific password: keep it 0600, keep it out of the",
    "# repository, and revoke it at appleid.apple.com if this file ever leaves the box.",
)
ICLOUD_ORDER = ("ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD", "ICLOUD_CALDAV_URL")


class Refused(Exception):
    """What was typed will not be written, and why — in words the panel can show."""


@dataclass(frozen=True)
class Target:
    provider: str
    path: Path
    required: tuple[str, ...]
    optional: tuple[str, ...]
    order: tuple[str, ...]
    header: tuple[str, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return self.required + self.optional


def targets() -> dict[str, Target]:
    """Where each provider's file lives. Built per call, so a test can point the environment
    variables at a temporary directory and never near a real credential."""
    return {
        "icloud": Target("icloud", icloud_config_path(),
                         ("ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD"),
                         ("ICLOUD_CALDAV_URL",), ICLOUD_ORDER, ICLOUD_HEADER),
        # The same header and order the OAuth module writes with, referenced rather than
        # repeated: two copies would agree until one of them was fixed.
        "google": Target("google", google_oauth.config_path(),
                         ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
                         ("GOOGLE_REDIRECT_URI",), google_oauth.ORDER, google_oauth.HEADER),
    }


def save(provider: str, fields: Mapping[str, str]) -> Target:
    """Write what one provider's file is allowed to hold, and nothing else."""
    target = targets().get(provider)
    if target is None:
        raise Refused(f"sundial keeps no credentials for {provider!r}")

    unknown = sorted(set(fields) - set(target.keys))
    if unknown:
        # Named, because the person typed it: "unknown field" without saying which one is a
        # puzzle, and a typo in a key name is the likeliest cause by a distance.
        raise Refused(
            f"{provider} takes {', '.join(target.keys)} — not {', '.join(unknown)}"
        )

    for key in target.required:
        if not str(fields.get(key, "")).strip():
            raise Refused(f"{SPOKEN.get(key, key)} is needed to connect {provider}")

    cleaned: dict[str, str] = {}
    for key, value in fields.items():
        # Stripped rather than refused: an app-specific password pasted from Apple's page
        # arrives with a space or a newline on the end more often than not, and refusing that
        # would be pedantry that looks like a wrong password.
        text = str(value).strip()
        if not text:
            continue
        if "\n" in text or "\r" in text:
            raise Refused(
                f"{SPOKEN.get(key, key)} has a line break in it. The file holds one key per "
                "line, so that is not a value — it is a second entry."
            )
        cleaned[key] = text

    env_file.write(target.path, cleaned, order=target.order, header=target.header)
    return target
