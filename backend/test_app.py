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
    sundial.init_db()
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
