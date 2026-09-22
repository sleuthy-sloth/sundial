"""What has to hold before a release, in one command.

    python3 scripts/smoke_release.py

Three things, against a throwaway database in a temporary directory, so this is safe to
run on the machine you actually use:

  1. a fresh start — no database at all, the app makes one and answers
  2. an upgrade with plans already in it — including a day in the old compact form, which
     the app has to repair rather than refuse
  3. a restore from backup — what was written after the copy is gone, what was written
     before it is there

The app is driven the way the service drives it: a new process per step, importing
`app:app` and going through its startup hook with SUNDIAL_DB pointing at the database
under test, because that is where the migrations run and only a real startup proves they
do. Needs the development requirements (`backend/requirements-dev.txt`) for the test
client.

Exits non-zero on the first thing that does not hold.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"

PROBE = r"""
import json, sys
from fastapi.testclient import TestClient
from app import app

request = json.loads(sys.argv[1])

# Entering the client is what runs the startup hook and therefore the migrations —
# the same path `uvicorn app:app` takes when the service comes up.
with TestClient(app) as client:
    if request["what"] == "day":
        answer = client.get(f"/api/day?day={request['day']}")
    elif request["what"] == "create":
        answer = client.post("/api/blocks", json=request["block"])
    else:
        raise SystemExit(f"unknown step: {request['what']}")

if answer.status_code >= 300:
    print(f"{request['what']} came back {answer.status_code}: {answer.text}", file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(answer.json()))
"""


def run(what: str, db: Path, **extra) -> dict:
    """Drive the app in its own process, the way the service does."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["SUNDIAL_DB"] = str(db)
    done = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps({"what": what, **extra})],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"the app failed to {what}:\n{done.stderr.strip()}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def schema_versions(db: Path) -> list[int]:
    conn = sqlite3.connect(db)
    try:
        return sorted(row[0] for row in conn.execute("SELECT version FROM schema_version"))
    finally:
        conn.close()


def main() -> int:
    failures: list[str] = []

    def check(name: str, held: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if held else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""))
        if not held:
            failures.append(name)

    work = Path(tempfile.mkdtemp(prefix="sundial-smoke-"))
    db = work / "smoke.db"
    try:
        print(f"a fresh start  ({work})")
        day = "2026-09-21"
        first = run("day", db, day=day)
        check("the app makes a database and answers", "blocks" in first)
        check("every migration runs", schema_versions(db) == [1, 2, 3, 4, 5, 6], str(schema_versions(db)))
        standup = run("create", db, block={"title": "Standup", "day": day, "start_min": 540, "duration_min": 30})
        check("a plan can be saved", standup.get("title") == "Standup")

        print("an upgrade with plans already in it")
        loose = run("create", db, block={"title": "Call the dentist", "duration_min": 15})
        old = run("create", db, block={"title": "Old plan", "day": day, "start_min": 600, "duration_min": 60})

        # Leave the database the way the previous version would have: a day in the compact
        # form, and the repair that knows about it not yet applied.
        conn = sqlite3.connect(db)
        conn.execute("UPDATE blocks SET day = ? WHERE id = ?", ("20260921", old["id"]))
        conn.execute("DELETE FROM schema_version WHERE version >= 3")
        conn.commit()
        conn.close()

        after = run("day", db, day=day)
        titles = [b["title"] for b in after["blocks"]]
        check("the app comes up on the older database", schema_versions(db) == [1, 2, 3, 4, 5, 6], str(schema_versions(db)))
        check("a day stored the old way is repaired", "Old plan" in titles)
        check("and found on the day it was meant for", any(b["id"] == old["id"] for b in after["blocks"]))
        check("the plans that were already fine are untouched", "Standup" in titles)
        check("the inbox is untouched", any(b["title"] == "Call the dentist" for b in after["inbox"]))

        print("a restore from backup")
        copy = work / "copy.db"
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / "backup.py"), "--db", str(db), "--to", str(copy)],
            check=True,
            capture_output=True,
        )
        run("create", db, block={"title": "Written after the copy", "day": day, "start_min": 780, "duration_min": 30})
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / "backup.py"), "--db", str(db), "--restore", str(copy)],
            check=True,
            capture_output=True,
        )
        restored = [b["title"] for b in run("day", db, day=day)["blocks"]]
        check("the copy brings the plans back", "Standup" in restored and "Old plan" in restored)
        check("and drops what was written after it", "Written after the copy" not in restored)

        print()
        if failures:
            print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
            return 1
        print("the release path holds: fresh start, upgrade with plans, restore")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
