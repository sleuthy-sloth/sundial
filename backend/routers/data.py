"""Taking everything out as a file, and putting one back.

The only destructive route in the app, and the only one that answers with a download. Both
are deliberate, and both are explained at the route rather than here.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

import export
from bootstrap import current_schema_version
from clock import today
from schemas.data import ImportIn
from store import db

router = APIRouter()

IMPORT_CONFIRMATION = "replace everything"


@router.get("/api/export")
def export_all() -> Response:
    """Everything sundial holds, as one JSON file.

    Served as a download rather than left to be fetched and saved by hand, because the
    filename is the only part of this that a person has to get right.
    """
    with db() as conn:
        document = export.dump(conn, current_schema_version(conn))
    return Response(
        content=json.dumps(document, indent=2, sort_keys=True) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="sundial-{today()}.json"'},
    )


@router.post("/api/import")
def import_all(body: ImportIn) -> dict:
    """Replace everything in the database with the contents of an export.

    Destructive on purpose, and confirmed on purpose: merging sounds gentler but has to
    guess whether two rows with the same id are one thing or two, and it guesses silently.
    "This is my data now" is a promise that can be kept, and the panel says so first.

    Two things it does not do. It does not touch `push_subscriptions`, so restoring your
    data cannot unsubscribe the phone in your pocket. And it does not leave you without a
    way back: the database being replaced is copied first, and the copy is named in the
    answer.
    """
    if body.confirm.strip().lower() != IMPORT_CONFIRMATION:
        raise HTTPException(
            400,
            f'an import replaces everything in sundial. Send "confirm": '
            f'"{IMPORT_CONFIRMATION}" to mean it',
        )
    with db() as conn:
        try:
            tables = export.check(body.document, current_schema_version(conn))
        except export.ExportError as exc:
            raise HTTPException(400, str(exc)) from None
        unknown = export.unknown_columns(body.document, conn)
        if unknown:
            named = ", ".join(f"{t}.{', '.join(c)}" for t, c in unknown.items())
            raise HTTPException(
                400,
                f"that file has columns sundial does not know: {named}. Nothing was changed",
            )
        kept = export.keep_copy(conn, export.database_file(conn))
        try:
            written = export.replace(conn, tables)
        except sqlite3.IntegrityError as exc:
            # A file whose rows contradict each other: two blocks sharing one id, or an event
            # naming a calendar the file does not carry. Left unhandled this is a 500 with a
            # stack trace and no explanation, which is the worst of both — the person learns
            # nothing and cannot tell whether it took. `replace` has already rolled back, so
            # the honest answer is available: a refusal that names what SQLite objected to.
            raise HTTPException(
                400, f"that file contradicts itself: {exc}. Nothing was changed"
            ) from None
        left_alone = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {
        "replaced": written,
        "kept": str(kept),
        "left_alone": {"push_subscriptions": left_alone},
    }
