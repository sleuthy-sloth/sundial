"""Templates: a day structure written once, and put on a day when you ask.

Six things are worth locking down here, and the plan names all six: creating, editing and
deleting a template; an item with no hour landing in Anytime; an item with an hour landing on
the clock; applying to a day that is not today; applying twice; and surviving an export.

The one that is easy to get subtly wrong is the fifth. Applying is additive — nothing is
overwritten, nothing is deduplicated, and two applies of the same template put two of everything
on the day. That is what the plan asks for, so it is asserted rather than left to reading.

Run with:  cd backend && .venv/bin/pytest -q
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

import app
import store

WEEKDAY = "2026-09-21"  # a Monday
ANOTHER = "2026-09-24"


@pytest.fixture
def client(database):
    """The real app over the test's database, without the lifespan's notification tick."""
    return TestClient(app.app)


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "sundial.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    app.bootstrap()
    return path


def workday(client):
    """The plan's own example: four items, three of them at a time of day."""
    res = client.post(
        "/api/templates",
        json={
            "name": "Workday",
            "items": [
                {"title": "Gym", "start_min": 390, "duration_min": 60, "color": "emerald"},
                {"title": "Commute", "start_min": 480, "duration_min": 30, "color": "sky"},
                {"title": "Lunch", "start_min": 720, "duration_min": 30, "color": "amber"},
                {"title": "Admin", "start_min": 960, "duration_min": 45, "color": "violet"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def blocks_on(client, day):
    return client.get(f"/api/day?day={day}").json()["blocks"]


# ---- create, read, rename, delete ---------------------------------------------------------

def test_a_template_is_created_with_its_items_in_order(client):
    made = workday(client)
    assert made["name"] == "Workday"
    assert [i["title"] for i in made["items"]] == ["Gym", "Commute", "Lunch", "Admin"]
    assert [i["sort_order"] for i in made["items"]] == [0, 1, 2, 3]
    assert made["created_at"] and made["updated_at"]

    listed = client.get("/api/templates").json()["templates"]
    assert [t["name"] for t in listed] == ["Workday"]
    assert len(listed[0]["items"]) == 4


def test_a_template_can_be_started_empty_and_filled_in_later(client):
    made = client.post("/api/templates", json={"name": "Travel day"}).json()
    assert made["items"] == []

    res = client.put(
        f"/api/templates/{made['id']}/blocks",
        json={"items": [{"title": "Passport", "duration_min": 15}]},
    )
    assert res.status_code == 200, res.text
    assert [i["title"] for i in res.json()["items"]] == ["Passport"]
    # The colour nobody named is the one a block's column would have defaulted to.
    assert res.json()["items"][0]["color"] == "slate"


def test_the_whole_item_list_is_replaced_in_the_order_it_arrives(client):
    made = workday(client)
    res = client.put(
        f"/api/templates/{made['id']}/blocks",
        json={
            "items": [
                {"title": "Admin", "start_min": 960, "duration_min": 45, "color": "violet"},
                {"title": "Gym", "start_min": 390, "duration_min": 60, "color": "emerald"},
            ]
        },
    )
    items = res.json()["items"]
    assert [i["title"] for i in items] == ["Admin", "Gym"]
    assert [i["sort_order"] for i in items] == [0, 1]

    # And emptying it is how you take the last line out.
    emptied = client.put(f"/api/templates/{made['id']}/blocks", json={"items": []}).json()
    assert emptied["items"] == []


def test_a_template_can_be_renamed(client):
    made = workday(client)
    res = client.patch(f"/api/templates/{made['id']}", json={"name": "Term-time workday"})
    assert res.status_code == 200
    assert res.json()["name"] == "Term-time workday"
    assert client.get("/api/templates").json()["templates"][0]["name"] == "Term-time workday"


def test_a_template_is_deleted_with_every_item_it_held(client):
    made = workday(client)
    assert client.delete(f"/api/templates/{made['id']}").status_code == 204
    assert client.get("/api/templates").json()["templates"] == []

    with store.db() as conn:
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM template_blocks WHERE template_id = ?", (made["id"],)
        ).fetchone()["n"]
    assert left == 0, "the items outlived the template they belonged to"


def test_a_template_can_be_duplicated_and_the_copy_is_its_own(client):
    made = workday(client)
    res = client.post(f"/api/templates/{made['id']}/duplicate", json={})
    assert res.status_code == 201, res.text
    copy = res.json()
    assert copy["id"] != made["id"]
    assert copy["name"] == "Workday copy"
    assert [i["title"] for i in copy["items"]] == [i["title"] for i in made["items"]]

    # Changing the copy leaves the original alone, which is the point of duplicating.
    client.put(f"/api/templates/{copy['id']}/blocks", json={"items": []})
    original = [t for t in client.get("/api/templates").json()["templates"]
                if t["id"] == made["id"]][0]
    assert len(original["items"]) == 4

    named = client.post(f"/api/templates/{made['id']}/duplicate", json={"name": "Term time"})
    assert named.json()["name"] == "Term time"


def test_a_template_that_is_not_there_is_a_sentence_not_a_500(client):
    assert client.patch("/api/templates/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/templates/nope").status_code == 404
    assert client.put("/api/templates/nope/blocks", json={"items": []}).status_code == 404
    assert client.post("/api/templates/nope/apply", json={"day": WEEKDAY}).status_code == 404
    assert client.post("/api/templates/nope/duplicate", json={}).status_code == 404

    missing = client.patch("/api/templates/nope", json={"name": "x"}).json()["detail"]
    assert "no such template" in missing


# ---- refusals read as sentences -----------------------------------------------------------

def test_an_item_without_a_title_or_with_a_bad_colour_is_refused(client):
    blank = client.post(
        "/api/templates", json={"name": "x", "items": [{"title": "   "}]}
    )
    assert blank.status_code == 400
    assert "title" in blank.json()["detail"]

    colour = client.post(
        "/api/templates",
        json={"name": "x", "items": [{"title": "Gym", "color": "chartreuse"}]},
    )
    assert colour.status_code == 400
    assert "unknown color" in colour.json()["detail"]


def test_a_template_needs_a_name(client):
    res = client.post("/api/templates", json={"name": "  "})
    assert res.status_code == 400
    assert "name" in res.json()["detail"]


def test_an_item_that_runs_past_midnight_is_refused(client):
    res = client.post(
        "/api/templates",
        json={"name": "x", "items": [{"title": "Too late", "start_min": 1430, "duration_min": 60}]},
    )
    assert res.status_code == 400
    assert "past midnight" in res.json()["detail"]


def test_a_refused_item_list_writes_nothing(client):
    made = workday(client)
    res = client.put(
        f"/api/templates/{made['id']}/blocks",
        json={"items": [
            {"title": "Fine", "start_min": 600, "duration_min": 30},
            {"title": "   ", "start_min": 660, "duration_min": 30},
        ]},
    )
    assert res.status_code == 400
    after = client.get("/api/templates").json()["templates"][0]
    assert [i["title"] for i in after["items"]] == ["Gym", "Commute", "Lunch", "Admin"], (
        "the first item of a refused list was written anyway"
    )


# ---- applying ------------------------------------------------------------------------------

def test_applying_puts_the_scheduled_items_on_the_day(client):
    workday(client)
    made = client.get("/api/templates").json()["templates"][0]
    res = client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY})
    assert res.status_code == 200, res.text
    assert len(res.json()["created"]) == 4

    on_the_day = blocks_on(client, WEEKDAY)
    assert [(b["title"], b["start_min"]) for b in on_the_day] == [
        ("Gym", 390), ("Commute", 480), ("Lunch", 720), ("Admin", 960),
    ]
    assert all(b["duration_min"] for b in on_the_day)
    assert all(b["day"] == WEEKDAY for b in on_the_day)
    assert all(b["done"] is False for b in on_the_day), "a plan is not a record of having done it"
    assert all(b["source"] == "block" for b in on_the_day), "an applied block is just a block"


def test_an_item_with_no_hour_lands_in_anytime(client):
    """The plan's one line about Anytime: no start_min means the inbox, not midnight."""
    client.post(
        "/api/templates",
        json={
            "name": "Reset",
            "items": [
                {"title": "Change the sheets", "duration_min": 20},
                {"title": "Bins out", "start_min": 1080, "duration_min": 15, "color": "teal"},
            ],
        },
    )
    made = client.get("/api/templates").json()["templates"][0]
    client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY})

    day = client.get(f"/api/day?day={WEEKDAY}").json()
    assert [(b["title"], b["start_min"]) for b in day["inbox"]] == [("Change the sheets", None)]
    assert [(b["title"], b["start_min"]) for b in day["blocks"]] == [("Bins out", 1080)]
    # An inbox item is not on any day, so it is not on this one either.
    assert day["blocks"][0]["day"] == WEEKDAY


def test_a_template_can_be_applied_to_any_day(client):
    made = workday(client)
    client.post(f"/api/templates/{made['id']}/apply", json={"day": ANOTHER})
    assert [b["title"] for b in blocks_on(client, ANOTHER)] == [
        "Gym", "Commute", "Lunch", "Admin",
    ]
    assert blocks_on(client, WEEKDAY) == []


def test_applying_twice_adds_everything_twice(client):
    """Additive, not idempotent. There is no "already applied" to notice, and no dedup."""
    made = workday(client)
    first = client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY}).json()
    second = client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY}).json()

    assert len(first["created"]) == 4 and len(second["created"]) == 4
    assert not set(first["created"]) & set(second["created"])
    on_the_day = blocks_on(client, WEEKDAY)
    assert len(on_the_day) == 8
    assert [b["title"] for b in on_the_day].count("Gym") == 2


def test_applying_adds_alongside_what_is_already_planned(client):
    """Nothing is overwritten and nothing is moved: overlaps are allowed and expected."""
    work = client.post(
        "/api/blocks",
        json={"title": "Standup", "day": WEEKDAY, "start_min": 390, "duration_min": 30},
    ).json()
    inbox = client.post("/api/blocks", json={"title": "Ring the bank"}).json()

    made = workday(client)
    client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY})

    on_the_day = blocks_on(client, WEEKDAY)
    assert len(on_the_day) == 5
    # The two things that were already there are untouched, hour and all. Gym overlaps
    # Standup — both at 6:30 — and both are drawn, in alphabetical order at that minute.
    standup = [b for b in on_the_day if b["id"] == work["id"]][0]
    assert (standup["title"], standup["start_min"], standup["duration_min"]) == ("Standup", 390, 30)
    assert {b["title"] for b in on_the_day if b["start_min"] == 390} == {"Standup", "Gym"}
    assert client.get("/api/day").json()["inbox"][0]["id"] == inbox["id"]


def test_applying_an_empty_template_is_refused_with_a_sentence(client):
    made = client.post("/api/templates", json={"name": "Nothing yet"}).json()
    res = client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY})
    assert res.status_code == 400
    assert "nothing in it" in res.json()["detail"]
    assert blocks_on(client, WEEKDAY) == [], "a refused apply wrote something anyway"


def test_a_day_that_is_not_a_day_is_refused(client):
    made = workday(client)
    res = client.post(f"/api/templates/{made['id']}/apply", json={"day": "20260921"})
    assert res.status_code == 400
    assert "YYYY-MM-DD" in res.json()["detail"]


def test_an_applied_block_is_an_ordinary_block(client):
    """A starting point, not a standing rule: from here it is edited and deleted like any other."""
    made = workday(client)
    created = client.post(f"/api/templates/{made['id']}/apply", json={"day": WEEKDAY}).json()
    gym = created["created"][0]

    assert client.patch(f"/api/blocks/{gym}", json={"title": "Gym (moved to 7)"}).status_code == 200
    assert client.patch(f"/api/blocks/{gym}", json={"start_min": 420}).status_code == 200
    assert client.delete(f"/api/blocks/{gym}").status_code == 204

    # ...and none of that touched the template.
    still_there = client.get("/api/templates").json()["templates"][0]
    assert [i["title"] for i in still_there["items"]][0] == "Gym"
    assert still_there["items"][0]["start_min"] == 390


# ---- the round trip over HTTP -------------------------------------------------------------

def test_a_template_survives_an_export_and_an_import(client):
    workday(client)
    document = client.get("/api/export").json()
    assert len(document["tables"]["templates"]) == 1
    assert len(document["tables"]["template_blocks"]) == 4

    with store.db() as conn:
        for name in ("templates", "template_blocks"):
            conn.execute(f"DELETE FROM {name}")
    assert client.get("/api/templates").json()["templates"] == []

    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["replaced"]["templates"] == 1
    assert answer.json()["replaced"]["template_blocks"] == 4

    restored = client.get("/api/templates").json()["templates"][0]
    assert [i["title"] for i in restored["items"]] == ["Gym", "Commute", "Lunch", "Admin"]
    assert [i["start_min"] for i in restored["items"]] == [390, 480, 720, 960]

    # And it still applies, which is the only thing a template is for.
    client.post(f"/api/templates/{restored['id']}/apply", json={"day": WEEKDAY})
    assert len(blocks_on(client, WEEKDAY)) == 4


def test_an_import_that_drops_the_template_tables_is_refused(client):
    """Missing and empty look the same once imported, so a partial file deletes the difference."""
    workday(client)
    document = client.get("/api/export").json()
    del document["tables"]["template_blocks"]
    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 400
    assert "template_blocks" in answer.json()["detail"]
    assert len(client.get("/api/templates").json()["templates"]) == 1, "the refusal changed nothing"
