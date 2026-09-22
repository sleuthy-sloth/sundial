"""The rules worth locking down: day and start_min travel together, and a block
cannot run past midnight. Run with:  cd backend && .venv/bin/pytest -q
"""

import importlib.util
import os
import pathlib
import shutil
import sqlite3
import tempfile

os.environ["SUNDIAL_DB"] = str(pathlib.Path(tempfile.mkdtemp()) / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as sundial  # noqa: E402
import bootstrap  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    sundial.DB_PATH.unlink(missing_ok=True)
    sundial.bootstrap()
    yield
    sundial.DB_PATH.unlink(missing_ok=True)


@pytest.fixture
def client():
    return TestClient(sundial.app)


def make(client, **kw):
    kw.setdefault("title", "thing")
    res = client.post("/api/blocks", json=kw)
    assert res.status_code == 201, res.text
    return res.json()


def test_inbox_block_has_no_time(client):
    b = make(client)
    assert b["day"] is None and b["start_min"] is None
    assert client.get("/api/day").json()["inbox"][0]["id"] == b["id"]


def test_scheduled_block_lands_on_its_day(client):
    make(client, title="standup", day="2026-09-21", start_min=9 * 60, duration_min=15)
    day = client.get("/api/day?day=2026-09-21").json()
    assert [b["title"] for b in day["blocks"]] == ["standup"]
    assert day["inbox"] == []


def test_start_time_without_a_day_is_rejected(client):
    res = client.post("/api/blocks", json={"title": "x", "start_min": 540})
    assert res.status_code == 400


def test_scheduled_without_a_start_time_is_rejected(client):
    res = client.post("/api/blocks", json={"title": "x", "day": "2026-09-21"})
    assert res.status_code == 400


def test_block_cannot_run_past_midnight(client):
    res = client.post(
        "/api/blocks",
        json={"title": "x", "day": "2026-09-21", "start_min": 1430, "duration_min": 60},
    )
    assert res.status_code == 400


def test_resizing_past_midnight_is_rejected(client):
    b = make(client, day="2026-09-21", start_min=1400, duration_min=30)
    res = client.patch(f"/api/blocks/{b['id']}", json={"duration_min": 120})
    assert res.status_code == 400


def test_setting_a_start_time_alone_puts_it_on_today(client):
    """Dragging from the inbox sends start_min; the day must follow."""
    b = make(client)
    out = client.patch(f"/api/blocks/{b['id']}", json={"start_min": 600}).json()
    assert out["day"] == sundial.today()
    assert out["start_min"] == 600


def test_unschedule_clears_both(client):
    b = make(client, day="2026-09-21", start_min=600)
    out = client.patch(f"/api/blocks/{b['id']}", json={"unschedule": True}).json()
    assert out["day"] is None and out["start_min"] is None
    assert client.get("/api/day?day=2026-09-21").json()["blocks"] == []


def test_dragging_to_another_day_keeps_the_time(client):
    b = make(client, day="2026-09-21", start_min=600)
    out = client.patch(f"/api/blocks/{b['id']}", json={"day": "2026-09-22"}).json()
    assert (out["day"], out["start_min"]) == ("2026-09-22", 600)


def test_bad_input_is_refused(client):
    assert client.get("/api/day?day=21-09-2026").status_code == 400
    assert client.post("/api/blocks", json={"title": ""}).status_code == 422
    b = make(client)
    assert client.patch(f"/api/blocks/{b['id']}", json={"color": "chartreuse"}).status_code == 400
    assert client.patch("/api/blocks/nope", json={"title": "x"}).status_code == 404


def test_delete_then_delete_again(client):
    b = make(client)
    assert client.delete(f"/api/blocks/{b['id']}").status_code == 204
    assert client.delete(f"/api/blocks/{b['id']}").status_code == 404


def test_health_reports_the_count(client):
    make(client)
    make(client)
    assert client.get("/api/health").json() == {"ok": True, "blocks": 2}


# ---- migrations ----
# The risk these cover: a fresh clone, or an existing database, left missing a column.


def test_a_fresh_database_lands_migrated():
    """Every migration on disk is applied, and each one's effect is visible."""
    sundial.DB_PATH.unlink(missing_ok=True)
    on_disk = sorted(int(p.name.split("_", 1)[0]) for p in sundial.MIGRATIONS.glob("*.sql"))

    assert sundial.bootstrap() == on_disk

    with sundial.db() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(blocks)")}
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        versions = [r["version"] for r in conn.execute("SELECT version FROM schema_version")]

    assert {"icon", "external_uid"} <= columns  # 001 and 002
    assert {"calendars", "events", "sync_log"} <= tables  # 002
    assert versions == on_disk


def test_bootstrap_is_idempotent():
    """A second run must apply nothing — re-running 001 would be a duplicate column."""
    assert sundial.bootstrap() == []
    assert sundial.bootstrap() == []


def test_a_migration_without_a_number_is_rejected():
    bad = sundial.MIGRATIONS / "oops.sql"
    bad.write_text("SELECT 1;")
    try:
        sundial.DB_PATH.unlink(missing_ok=True)
        with pytest.raises(RuntimeError, match="must start with a number"):
            sundial.bootstrap()
    finally:
        bad.unlink()


# ---- icons ----


def test_icon_round_trips(client):
    b = make(client, title="yoga", icon="🧘")
    assert b["icon"] == "🧘"
    assert client.patch(f"/api/blocks/{b['id']}", json={"icon": "🧾"}).json()["icon"] == "🧾"
    assert client.patch(f"/api/blocks/{b['id']}", json={"icon": ""}).json()["icon"] == ""
    assert client.get("/api/day").json()["inbox"][0]["icon"] == ""


def test_an_absurd_icon_is_refused(client):
    assert client.post("/api/blocks", json={"title": "x", "icon": "x" * 20}).status_code == 422


# ---- the week strip ----


def test_week_counts_each_day(client):
    make(client, title="a", day="2026-09-21", start_min=540, duration_min=30)
    make(client, title="b", day="2026-09-21", start_min=600, duration_min=45)
    make(client, title="c", day="2026-09-23", start_min=600, duration_min=60)
    make(client, title="an inbox item")  # has no day, so it belongs to no day's load

    week = client.get("/api/week?start=2026-09-21").json()
    assert [d["day"] for d in week["days"]] == [f"2026-09-{n}" for n in range(21, 28)]
    load = {d["day"]: (d["blocks"], d["minutes"]) for d in week["days"]}
    assert load["2026-09-21"] == (2, 75)
    assert load["2026-09-22"] == (0, 0)
    assert load["2026-09-23"] == (1, 60)


def test_week_window_is_bounded_and_validated(client):
    assert len(client.get("/api/week?days=999").json()["days"]) == 31
    assert len(client.get("/api/week?days=0").json()["days"]) == 1
    assert client.get("/api/week?start=nope").status_code == 400


# ---- the API contract ----
# What these cover: payloads SQLite or the date parser can be made to reject *after*
# the request was accepted. The failure mode is a 500, which is the worst of both
# worlds — the row is untouched either way, but the caller cannot tell a refusal from
# a broken server, and the client has no message worth showing.


def reload_block(client, block_id):
    """The block as the API reports it, from whichever list it is in."""
    data = client.get("/api/day?day=2026-09-21").json()
    for block in [*data["blocks"], *data["inbox"]]:
        if block["id"] == block_id:
            return block
    raise AssertionError(f"block {block_id} is gone")


REFUSED_NULLS = ["title", "duration_min", "color", "icon", "notes", "done"]


@pytest.mark.parametrize("field", REFUSED_NULLS)
def test_explicit_null_on_a_column_that_cannot_hold_one_is_a_4xx(client, field):
    b = make(client, title="standup", day="2026-09-21", start_min=600)
    before = reload_block(client, b["id"])

    res = client.patch(f"/api/blocks/{b['id']}", json={field: None})

    assert res.status_code == 400, res.text
    assert isinstance(res.json()["detail"], str), "the client needs a message it can print"
    assert reload_block(client, b["id"]) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"day": "2026-09-22", "start_min": None},  # a day with no time
        {"day": None, "start_min": 700},  # a time with no day
    ],
)
def test_a_half_scheduled_block_is_refused(client, changes):
    b = make(client, title="standup", day="2026-09-21", start_min=600)
    before = reload_block(client, b["id"])

    res = client.patch(f"/api/blocks/{b['id']}", json=changes)

    assert res.status_code == 400, res.text
    assert reload_block(client, b["id"]) == before


def test_nulling_both_halves_together_still_unschedules(client):
    b = make(client, day="2026-09-21", start_min=600)
    out = client.patch(f"/api/blocks/{b['id']}", json={"day": None, "start_min": None}).json()
    assert (out["day"], out["start_min"]) == (None, None)


def test_a_whitespace_only_title_is_refused(client):
    b = make(client)

    res = client.patch(f"/api/blocks/{b['id']}", json={"title": "   "})
    assert res.status_code == 400, res.text
    assert reload_block(client, b["id"])["title"] == "thing"

    assert client.post("/api/blocks", json={"title": "\t \n"}).status_code == 400
    assert client.get("/api/health").json()["blocks"] == 1


def test_a_title_is_stored_without_its_padding(client):
    assert make(client, title="  standup  ")["title"] == "standup"
    b = make(client)
    out = client.patch(f"/api/blocks/{b['id']}", json={"title": "  standup again  "}).json()
    assert out["title"] == "standup again"


def test_creating_with_an_unknown_colour_is_refused(client):
    res = client.post("/api/blocks", json={"title": "x", "color": "chartreuse"})
    assert res.status_code == 400, res.text
    assert client.get("/api/health").json()["blocks"] == 0


@pytest.mark.parametrize("color", sundial.PALETTE)
def test_create_and_patch_agree_on_every_palette_colour(client, color):
    b = make(client, title="paint", color=color)
    assert b["color"] == color
    assert client.patch(f"/api/blocks/{b['id']}", json={"color": color}).status_code == 200


BAD_DAYS = [
    "20260921",  # the compact form the parser used to accept
    "2026-9-1",  # right shape, unpadded
    "26-09-21",
    "2026/09/21",
    "2026-09-21T00:00:00",
    "2026-13-01",
    "2026-09-32",
]


@pytest.mark.parametrize("day", BAD_DAYS)
def test_a_non_canonical_day_is_refused_everywhere(client, day):
    res = client.post("/api/blocks", json={"title": "x", "day": day, "start_min": 600})
    assert res.status_code == 400, res.text
    assert client.get("/api/day", params={"day": day}).status_code == 400
    assert client.get("/api/week", params={"start": day}).status_code == 400
    assert client.get("/api/health").json()["blocks"] == 0


def test_every_accepted_scheduled_block_can_be_fetched_back(client):
    """The reason for refusing odd input: what the API stores, the API must find."""
    for n in range(6):
        make(client, title=f"block {n}", day="2026-09-21", start_min=600 + n * 30, duration_min=15)

    assert len(client.get("/api/day?day=2026-09-21").json()["blocks"]) == 6
    assert client.get("/api/week?start=2026-09-21").json()["days"][0]["blocks"] == 6


def test_a_week_range_that_runs_off_the_calendar_is_refused(client):
    res = client.get("/api/week", params={"start": "9999-12-31", "days": 31})
    assert res.status_code == 400, res.text
    assert client.get("/api/week", params={"start": "9999-12-31", "days": 1}).status_code == 200


def test_the_day_repair_rewrites_a_compact_date_already_stored(client):
    """An installation that stored '20260921' before the refusal existed gets it back."""
    with sundial.db() as conn:
        conn.execute(
            "INSERT INTO blocks (id, title, day, start_min, duration_min, color, icon, notes,"
            " done, updated_at) VALUES ('legacy', 'old row', '20260921', 600, 30, 'slate', '',"
            " '', 0, '2026-09-20T00:00:00')"
        )
        # From 3 up, not just 3: the repair is replayed by removing its version record, and
        # any later migration has to go with it or MAX(version) still reads past 3 and the
        # runner correctly decides it has nothing to do.
        conn.execute("DELETE FROM schema_version WHERE version >= 3")

    assert sundial.migrate() == [3, 4, 5]

    with sundial.db() as conn:
        rows = list(conn.execute("SELECT day FROM blocks WHERE id = 'legacy'"))
    assert rows[0]["day"] == "2026-09-21"

    found = client.get("/api/day?day=2026-09-21").json()["blocks"]
    assert [b["title"] for b in found] == ["old row"]


# ---- the database, not the API ----


def test_the_connection_is_closed_when_the_block_ends():
    """`with conn` commits and rolls back but does not close — the file handle and the
    WAL reader survive until the garbage collector happens to run."""
    with sundial.db() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_a_failed_write_leaves_no_half_row():
    with pytest.raises(RuntimeError):
        with sundial.db() as conn:
            conn.execute(
                "INSERT INTO blocks (id, title, duration_min, color, icon, notes, done,"
                " updated_at) VALUES ('half', 'half a row', 30, 'slate', '', '', 0, 'x')"
            )
            raise RuntimeError("something went wrong after the write")

    with sundial.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"] == 0


def test_app_connections_enforce_foreign_keys():
    with sundial.db() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_deleting_a_calendar_takes_its_events_with_it():
    """002 declares ON DELETE CASCADE. It does nothing unless the connection turns
    foreign keys on, which is off by default and was never turned on."""
    with sundial.db() as conn:
        conn.execute("INSERT INTO calendars (ref, provider, name) VALUES ('c1', 'icloud', 'Home')")
        conn.execute(
            "INSERT INTO events (id, calendar_ref, provider, uid, title, start_utc, end_utc,"
            " updated_at) VALUES ('e1', 'c1', 'icloud', 'u1', 'Standup',"
            " '2026-09-21T16:00:00+00:00', '2026-09-21T16:30:00+00:00', '2026-09-21T00:00:00+00:00')"
        )

    with sundial.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 1
        conn.execute("DELETE FROM calendars WHERE ref = 'c1'")

    with sundial.db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0


def test_a_failing_migration_leaves_nothing_behind(tmp_path, monkeypatch):
    """A migration that dies half way must not leave the schema advanced without the
    version record — that combination cannot be retried or repaired by rerunning."""
    staged = tmp_path / "migrations"
    staged.mkdir()
    for sql in sundial.MIGRATIONS.glob("*.sql"):
        shutil.copy(sql, staged)
    # The runner reads the directory from the module it lives in, so what is patched is
    # `bootstrap` — the module that owns `migrate` — rather than the `app` name that
    # re-exports it.
    monkeypatch.setattr(bootstrap, "MIGRATIONS", staged)

    probe = staged / "900_probe.sql"
    probe.write_text("ALTER TABLE blocks ADD COLUMN probe TEXT;\nSELECT * FROM no_such_table;\n")

    with pytest.raises(sqlite3.OperationalError):
        sundial.migrate()

    with sundial.db() as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(blocks)")}
        versions = [r["version"] for r in conn.execute("SELECT version FROM schema_version")]

    assert "probe" not in columns, "the DDL from a failed migration is still in the schema"
    assert 900 not in versions

    probe.write_text("ALTER TABLE blocks ADD COLUMN probe TEXT;\n")
    assert sundial.migrate() == [900], "the corrected migration cannot be applied"
    with sundial.db() as conn:
        assert "probe" in {r["name"] for r in conn.execute("PRAGMA table_info(blocks)")}


def test_the_backup_script_points_at_the_database_the_app_uses():
    """Two places work out the default path. If they drift, the backup quietly copies
    something other than the database the app is serving."""
    spec = importlib.util.spec_from_file_location(
        "sundial_backup_for_app",
        pathlib.Path(sundial.__file__).resolve().parent.parent / "scripts" / "backup.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.default_db_path() == sundial.DB_PATH
