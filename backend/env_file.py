"""A key=value file next to the app: read plainly, written 0600 by rename.

Both credential files are the same kind of thing — a handful of keys, never in the
repository, never in the database, never in a log, re-read at every sync — so the writing is
one implementation rather than two that agree until one of them is fixed.

The temporary file is opened 0600 from the start and moved into place by rename, so a secret
is never briefly world-readable between being written and being chmod-ed, and a reader never
sees half a file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence


def read(path: str | Path) -> dict[str, str]:
    """The KEY=value lines, comments and blank lines ignored. A missing file reads empty."""
    p = Path(path)
    if not p.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write(
    path: str | Path,
    values: Mapping[str, str],
    *,
    order: Sequence[str] = (),
    header: Sequence[str] = (),
) -> None:
    """Merge keys into the file on disk, 0600, written by rename.

    A merge rather than a rewrite: these files hold things a person pasted in by hand, and the
    app adding a refresh token to one must not be a way to lose the client secret alongside it.
    Empty values are left out rather than written as a bare key — "unset" is not a value to
    store, and a blank line reads back as a key that is missing.
    """
    p = Path(path)
    merged = read(p)
    merged.update({key: value for key, value in values.items() if value})

    lines = list(header)
    for key in list(order) + sorted(set(merged) - set(order)):
        if merged.get(key):
            lines.append(f"{key}={merged[key]}")
    body = "\n".join(lines) + "\n"

    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(temporary, p)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    os.chmod(p, 0o600)
