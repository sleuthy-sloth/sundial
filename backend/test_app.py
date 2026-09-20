"""The rules worth locking down: day and start_min travel together, and a block
cannot run past midnight. Run with:  cd backend && .venv/bin/pytest -q
"""

import os
import pathlib
import tempfile

os.environ["SUNDIAL_DB"] = str(pathlib.Path(tempfile.mkdtemp()) / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as sundial  # noqa: E402


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
    sundial.DB_PATH.unlink(missing_ok=True)
    assert sundial.bootstrap() == [1]
    with sundial.db() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(blocks)")}
        versions = [r["version"] for r in conn.execute("SELECT version FROM schema_version")]
    assert "icon" in cols
    assert versions == [1]


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
