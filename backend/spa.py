"""Serving the built app, with a cache policy that does not lie about the files.

The build is asymmetric, and that decides everything here: `/assets/*` carries a
content hash in its name, so a file there can be kept for a year — the name changes when
the contents do. The shell, the manifest and the service worker do NOT change their
names, so they are the ones a browser can hold onto and hand back long after a deploy.

Starlette sends an ETag and a Last-Modified and no Cache-Control at all, which leaves the
browser to guess a freshness lifetime from the file's age (heuristic caching). That guess
is how a phone ends up opening the previous app for a while after an upgrade, and why the
service worker script itself can go stale. Saying `no-cache` out loud means "you may keep
this, but ask before using it" — cheap, because the ETag turns the question into a 304.
"""

from __future__ import annotations

from fastapi.staticfiles import StaticFiles

HASHED = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def cache_control_for(path: str) -> str:
    """What may be done with one file in the built app, given its path inside it."""
    return HASHED if path.startswith("assets/") else REVALIDATE


class SpaStaticFiles(StaticFiles):
    """StaticFiles that says how long each file may be kept, and never guesses."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = cache_control_for(path.lstrip("/"))
        return response
