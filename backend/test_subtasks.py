"""A task can hold a checklist: the lines, where they live, and what they must not change.

Six promises are on trial here, and four of them are about what a checklist must *not* do — which
is the whole risk of the feature. A line that counted towards the day would inflate the plan; a
line that rolled over on its own would be an orphan; a line that finished its task would be a
derived state; a line that lived on a day would be invisible.

The two that are about what it must do are the plain ones: a task can hold a list of steps and
they can be ticked, and a ticked box is still ticked after a reload. That last one is worth more
than it looks. A routine's occurrences are calculated rather than stored, so the obvious
implementation of a checklist on one — write the checkbox into the row that does not exist — gives
boxes that reset every time the page is loaded. The test below ticks one, asks the day again, and
ticks it again on a day that is not the same day.

Run with:  cd backend && .venv/bin/pytest -q
"""

import pytest
from fastapi.testclient import TestClient

import app
import export
import store
from clock import today
from services import rollover

TODAY = today()
YESTERDAY = rollover.day_before(TODAY)
TOMORROW = "2027-03-09"

# A Monday, and the day after it, for the routine whose days are worked out rather than stored.
MON = "2027-03-08"
TUE = "2027-03-09"


@pytest.fixture
def database(tmp_path, monkeypatch):
    """A real database — this app's own schema — in a file of this test's own."""
    path = tmp_path / "sundial.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    app.bootstrap()
    return path


@pytest.fixture
def client(database):
    return TestClient(app.app)


def block(client, **kw) -> dict:
    kw.setdefault("title", "Pack for the trip")
    kw.setdefault("duration_min", 30)
    res = client.post("/api/blocks", json=kw)
    assert res.status_code == 201, res.text
    return res.json()


def line(client, parent, title, **kw) -> dict:
    kw.setdefault("duration_min", 5)
    res = client.post("/api/blocks", json={"title": title, "parent_id": parent["id"], **kw})
    assert res.status_code == 201, res.text
    return res.json()


def pack(client, day=TODAY, *titles) -> dict:
    """A task on a day with a checklist under it, which is the whole feature in one helper."""
    parent = block(client, day=day, start_min=9 * 60)
    for title in titles or ("Passport", "Charger", "Meds"):
        line(client, parent, title)
    return parent


def day_view(client, day=TODAY) -> dict:
    answer = client.get(f"/api/day?day={day}")
    assert answer.status_code == 200, answer.text
    return answer.json()


def found(client, day, block_id) -> dict:
    """One block out of the day view, by id."""
    for item in day_view(client, day)["blocks"]:
        if item["id"] == block_id:
            return item
    raise AssertionError(f"{block_id} is not on {day}")


def routine(client, **kw) -> dict:
    kw.setdefault("title", "Gym")
    kw.setdefault("start_min", 6 * 60 + 30)
    kw.setdefault("duration_min", 60)
    kw.setdefault("recurrence_kind", "daily")
    kw.setdefault("start_date", MON)
    res = client.post("/api/routines", json=kw)
    assert res.status_code == 201, res.text
    return res.json()


def routine_line(client, rule, title) -> dict:
    res = client.post(f"/api/routines/{rule['id']}/subtasks", json={"title": title})
    assert res.status_code == 201, res.text
    return res.json()


def occurrence(client, rule, day) -> dict | None:
    for item in day_view(client, day)["blocks"]:
        if item.get("routine_id") == rule["id"]:
            return item
    return None


def tick(client, rule, day, line_id, done=True) -> dict:
    res = client.patch(
        f"/api/routines/{rule['id']}/occurrences/{day}/subtasks/{line_id}", json={"done": done}
    )
    assert res.status_code == 200, res.text
    return res.json()


def count(table: str) -> int:
    with store.db() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


# ---- a task holds a list of steps ------------------------------------------------------------


def test_a_line_is_created_under_its_task(client):
    """The shape of a line: a title, a parent, and no day and no hour of its own."""
    parent = block(client, day=TODAY, start_min=9 * 60)
    made = line(client, parent, "Passport")

    assert (made["title"], made["parent_id"]) == ("Passport", parent["id"])
    assert made["day"] is None and made["start_min"] is None
    assert made["done"] is False
    # A line is a block row, so the whole block API addresses it — which is what keeps ticking,
    # renaming and removing it from needing routes of their own.
    assert made["source"] == "block" and made["subtasks"] == []


def test_the_lines_come_back_nested_on_their_task_in_order(client):
    """Not as siblings: a client asking for the day gets a task with a list on it."""
    parent = pack(client, TODAY, "Passport", "Charger", "Meds")

    day = day_view(client)
    assert [b["title"] for b in day["blocks"]] == ["Pack for the trip"], "a line was its own row"
    assert [s["title"] for s in day["blocks"][0]["subtasks"]] == ["Passport", "Charger", "Meds"]
    assert [s["sort_order"] for s in day["blocks"][0]["subtasks"]] == [0, 1, 2]

    # And the task itself is unchanged by having one: same row, same hour, same length.
    assert (day["blocks"][0]["start_min"], day["blocks"][0]["duration_min"]) == (540, 30)
    assert parent["subtasks"] == []


def test_the_order_the_lines_were_written_in_is_what_comes_back(client):
    parent = block(client, day=TODAY, start_min=9 * 60)
    for title in ("Meds", "Passport", "Charger"):
        line(client, parent, title)

    assert [s["title"] for s in found(client, TODAY, parent["id"])["subtasks"]] == [
        "Meds", "Passport", "Charger"
    ]


def test_a_line_has_no_day_of_its_own_and_cannot_be_given_one(client):
    """A line is inside its task. Every way of putting it on the day is refused, with a sentence."""
    parent = block(client, day=TODAY, start_min=9 * 60)
    made = line(client, parent, "Passport")

    res = client.post(
        "/api/blocks", json={"title": "Orphan", "parent_id": parent["id"], "day": TODAY,
                             "start_min": 600}
    )
    assert res.status_code == 400 and "inside its task" in res.json()["detail"], res.text

    res = client.patch(f"/api/blocks/{made['id']}", json={"day": TODAY, "start_min": 600})
    assert res.status_code == 400 and "inside its task" in res.json()["detail"], res.text

    res = client.patch(f"/api/blocks/{made['id']}", json={"unschedule": True})
    assert res.status_code == 400, res.text

    # And nothing it is allowed to change moves it off the task: the row is where it was.
    res = client.patch(f"/api/blocks/{made['id']}", json={"title": "Passport (old one)"})
    assert res.status_code == 200, res.text
    assert res.json()["parent_id"] == parent["id"]


def test_a_line_cannot_hold_lines_of_its_own(client):
    """One level. A checklist under a checklist is a document, and this app is a day."""
    parent = block(client)
    made = line(client, parent, "Passport")

    res = client.post("/api/blocks", json={"title": "Photo page", "parent_id": made["id"]})
    assert res.status_code == 400, res.text
    assert "its own" in res.json()["detail"]

    res = client.post("/api/blocks", json={"title": "Nowhere", "parent_id": "nobody"})
    assert res.status_code == 404, res.text


def test_an_inbox_task_keeps_its_checklist_and_stays_one_item(client):
    """The Anytime path: a task waiting for a time still holds its steps, and they wait with it."""
    parent = block(client, title="Renew the passport")
    line(client, parent, "Photo")
    line(client, parent, "Form")

    day = day_view(client)
    assert [b["title"] for b in day["inbox"]] == ["Renew the passport"], "a line waited on its own"
    assert [s["title"] for s in day["inbox"][0]["subtasks"]] == ["Photo", "Form"]

    # Giving the task a time takes the steps with it, because they never had a day to leave.
    client.patch(f"/api/blocks/{parent['id']}", json={"day": TODAY, "start_min": 600})
    day = day_view(client)
    assert day["inbox"] == []
    assert [s["title"] for s in found(client, TODAY, parent["id"])["subtasks"]] == [
        "Photo", "Form"
    ]


# ---- what a checklist must not change --------------------------------------------------------


def test_a_checklist_is_inside_its_task_and_costs_the_day_nothing(client):
    """D2: a parent with three five-minute lines is still one thirty-minute block.

    The week's arithmetic is a union of what is on the clock, and the number this protects is the
    one v0.11 fixed: three overlapping blocks reported 165 minutes against a true 120. A line has
    no hour at all, so counting one is not a subtle overlap — it is a step being billed as a task.
    """
    parent = block(client, day=TODAY, start_min=9 * 60, duration_min=30)
    for title in ("Passport", "Charger", "Meds"):
        line(client, parent, title, duration_min=5)

    week = client.get(f"/api/week?start={TODAY}&days=1").json()["days"][0]
    assert week["planned_minutes"] == 30, "the lines were counted into the plan"
    assert week["minutes"] == 30, "the old sum-of-durations count included the lines"
    assert week["block_count"] == 1, "a line was counted as a block on the clock"
    assert week["open_minutes"] == 1440 - 30

    blocks = day_view(client)["blocks"]
    assert len(blocks) == 1 and len(blocks[0]["subtasks"]) == 3


def test_ticking_a_line_does_not_finish_the_task_and_finishing_the_task_does_not_tick_one(client):
    """D3: two independent statements. No derived states, no cascade, no guilt."""
    parent = pack(client, TODAY, "Passport", "Charger")
    lines = found(client, TODAY, parent["id"])["subtasks"]

    for made in lines:
        client.patch(f"/api/blocks/{made['id']}", json={"done": True})

    after = found(client, TODAY, parent["id"])
    assert [s["done"] for s in after["subtasks"]] == [True, True]
    assert after["done"] is False, "the last ticked line finished the task"

    client.patch(f"/api/blocks/{parent['id']}", json={"done": True})
    untouched = block(client, day=TODAY, start_min=11 * 60, title="Packing list")
    line(client, untouched, "Socks")
    assert found(client, TODAY, untouched["id"])["subtasks"][0]["done"] is False
    assert found(client, TODAY, parent["id"])["subtasks"][0]["done"] is True


def test_an_unfinished_task_rolls_over_with_its_checklist_as_one_item(client):
    """D4: the lines ride on the task's line, and a line is never its own row to be moved."""
    parent = block(client, title="Pack for the trip", day=YESTERDAY, start_min=600)
    line(client, parent, "Passport")
    ticked = line(client, parent, "Charger")
    client.patch(f"/api/blocks/{ticked['id']}", json={"done": True})

    leftover = day_view(client, TODAY)["leftover"]
    assert [b["title"] for b in leftover] == ["Pack for the trip"], "a line was offered on its own"
    assert [s["title"] for s in leftover[0]["subtasks"]] == ["Passport", "Charger"]
    assert [s["done"] for s in leftover[0]["subtasks"]] == [False, True]

    # Moving it to today moves the task: the lines never had a day of their own to be left behind.
    client.patch(f"/api/blocks/{parent['id']}", json={"day": TODAY, "start_min": 600})
    assert day_view(client, TODAY)["leftover"] == []
    moved = found(client, TODAY, parent["id"])
    assert [s["title"] for s in moved["subtasks"]] == ["Passport", "Charger"]
    assert [s["done"] for s in moved["subtasks"]] == [False, True]
    assert count("blocks") == 3, "moving the task left something behind"


def test_the_palette_and_the_health_count_are_about_tasks_not_steps(client):
    """A line is part of a task rather than a thing on a day, in the two places that count them."""
    first = block(client, title="One")
    assert client.get("/api/health").json()["blocks"] == 1

    line(client, first, "Step one")
    line(client, first, "Step two")
    assert client.get("/api/health").json()["blocks"] == 1, "a step counted as a task"

    # Colours rotate one per task, so two tasks in a row are two colours even with steps between.
    second = block(client, title="Two")
    third = block(client, title="Three")
    assert len({first["color"], second["color"], third["color"]}) == 3


def test_deleting_a_task_takes_its_checklist_with_it(client):
    """An orphaned line is the thing this feature was most likely to leave behind."""
    parent = block(client, day=TODAY, start_min=600)
    line(client, parent, "Passport")
    line(client, parent, "Charger")

    assert client.delete(f"/api/blocks/{parent['id']}").status_code == 204
    assert count("blocks") == 0, "the lines outlived their task"


# ---- a routine's checklist: definitions on the rule, ticks on the day -------------------------


def test_a_ticked_box_on_a_routine_is_still_ticked_when_the_day_is_read_again(client):
    """D5, and the check the whole design exists for.

    An occurrence is calculated, so there is no row for a checkbox to live in — the obvious
    implementation puts the state somewhere that is rebuilt on every read, and the boxes reset.
    This reads the day twice, and then reads a second day, because "it survived one reload" and
    "it is stored per day" are two different claims.
    """
    rule = routine(client)
    rule = routine_line(client, rule, "Bottle")
    rule = routine_line(client, rule, "Towel")
    first, second = rule["subtasks"][0]["id"], rule["subtasks"][1]["id"]

    assert [s["done"] for s in occurrence(client, rule, MON)["subtasks"]] == [False, False]

    tick(client, rule, MON, first)
    again = occurrence(client, rule, MON)
    assert [s["done"] for s in again["subtasks"]] == [True, False], "the box reset on a reload"
    assert [s["title"] for s in again["subtasks"]] == ["Bottle", "Towel"]

    # The rule's other day starts clean, and nothing was written to `blocks` to make any of this
    # work: the zero-generated-rows property is the reason routines are cheap and it is still true.
    assert [s["done"] for s in occurrence(client, rule, TUE)["subtasks"]] == [False, False]
    assert count("blocks") == 0

    # Ticking a line is not finishing the occurrence, and finishing the occurrence is not ticking
    # its lines: the two statements are separate, in both directions.
    assert occurrence(client, rule, MON)["done"] is False
    tick(client, rule, MON, second)
    client.patch(f"/api/routines/{rule['id']}/occurrences/{MON}", json={"done": True})
    after = occurrence(client, rule, MON)
    assert after["done"] is True and [s["done"] for s in after["subtasks"]] == [True, True]

    # Unticking says so, and a day that ends up saying nothing is not an override any more.
    tick(client, rule, MON, first, done=False)
    tick(client, rule, MON, second, done=False)
    client.patch(f"/api/routines/{rule['id']}/occurrences/{MON}", json={"done": False})
    assert [s["done"] for s in occurrence(client, rule, MON)["subtasks"]] == [False, False]
    assert count("routine_overrides") == 0, "a day that says nothing kept a row"


def test_the_rules_checklist_is_the_rules_and_editing_it_edits_every_day(client):
    """A line belongs to the rule, so adding one adds it to the days that already happened too."""
    rule = routine(client)
    assert occurrence(client, rule, MON)["subtasks"] == []
    assert occurrence(client, rule, TUE)["subtasks"] == []

    rule = routine_line(client, rule, "Bottle")
    line_id = rule["subtasks"][0]["id"]
    assert [s["title"] for s in occurrence(client, rule, MON)["subtasks"]] == ["Bottle"]
    assert [s["title"] for s in occurrence(client, rule, TUE)["subtasks"]] == ["Bottle"]

    renamed = client.patch(
        f"/api/routines/{rule['id']}/subtasks/{line_id}", json={"title": "Water bottle"}
    )
    assert renamed.status_code == 200, renamed.text
    # The id survived the rename, which is what keeps a tick pointing at the same line.
    assert [s["id"] for s in renamed.json()["subtasks"]] == [line_id]
    assert [s["title"] for s in occurrence(client, rule, MON)["subtasks"]] == ["Water bottle"]

    answer = client.delete(f"/api/routines/{rule['id']}/subtasks/{line_id}")
    assert answer.status_code == 204, answer.text
    assert occurrence(client, rule, MON)["subtasks"] == []


def test_a_tick_on_a_line_that_is_not_the_rules_is_refused(client):
    """Two rules, and a line id from the wrong one: a 404 rather than a tick that goes nowhere."""
    one = routine_line(client, routine(client, title="Gym"), "Bottle")
    other = routine(client, title="Ring")

    res = client.patch(
        f"/api/routines/{other['id']}/occurrences/{MON}/subtasks/{one['subtasks'][0]['id']}",
        json={"done": True},
    )
    assert res.status_code == 404, res.text

    # And a day the rule does not reach is still a refusal, checklist or not.
    res = client.patch(
        f"/api/routines/{other['id']}/occurrences/2027-02-01/subtasks/"
        f"{one['subtasks'][0]['id']}",
        json={"done": True},
    )
    assert res.status_code == 400, res.text


def test_back_to_the_routine_clears_the_boxes_too(client):
    rule = routine_line(client, routine(client), "Bottle")
    tick(client, rule, MON, rule["subtasks"][0]["id"])

    answer = client.delete(f"/api/routines/{rule['id']}/occurrences/{MON}")
    assert answer.status_code == 200, answer.text
    assert occurrence(client, rule, MON)["subtasks"][0]["done"] is False
    assert count("routine_overrides") == 0


# ---- templates carry checklists, and so does the file ---------------------------------------


def template(client, name="Travel day") -> dict:
    res = client.post(
        "/api/templates",
        json={
            "name": name,
            "items": [
                {
                    "title": "Pack for the trip",
                    "start_min": 540,
                    "duration_min": 30,
                    "color": "sky",
                    "subtasks": [{"title": "Passport"}, {"title": "Charger", "duration_min": 5}],
                },
                {"title": "Print the tickets", "color": "amber"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_a_template_holds_ordered_lines_and_applying_copies_them(client):
    """D6: the same additive copy a template already does, one level down."""
    stored = template(client)
    assert [i["title"] for i in stored["items"]] == ["Pack for the trip", "Print the tickets"]
    assert [s["title"] for s in stored["items"][0]["subtasks"]] == ["Passport", "Charger"]
    assert [s["start_min"] for s in stored["items"][0]["subtasks"]] == [None, None], (
        "a line was stored with an hour of its own"
    )

    answer = client.post(f"/api/templates/{stored['id']}/apply", json={"day": TODAY})
    assert answer.status_code == 200, answer.text
    assert len(answer.json()["created"]) == 2, "a line was reported as its own block"

    day = day_view(client)
    packed = next(b for b in day["blocks"] + day["inbox"] if b["title"] == "Pack for the trip")
    assert [s["title"] for s in packed["subtasks"]] == ["Passport", "Charger"]
    assert [s["done"] for s in packed["subtasks"]] == [False, False]

    # The Anytime item keeps its own lines, and Anytime is where it lands.
    waiting = next(b for b in day["inbox"] if b["title"] == "Print the tickets")
    assert waiting["subtasks"] == []

    # Additive, lines included: a second apply is a second of everything.
    client.post(f"/api/templates/{stored['id']}/apply", json={"day": TODAY})
    copies = [b for b in day_view(client)["blocks"] if b["title"] == "Pack for the trip"]
    assert len(copies) == 2 and all(len(b["subtasks"]) == 2 for b in copies)


def test_duplicating_a_template_copies_its_lines(client):
    stored = template(client)
    copy = client.post(f"/api/templates/{stored['id']}/duplicate", json={}).json()
    assert [s["title"] for s in copy["items"][0]["subtasks"]] == ["Passport", "Charger"]


def test_a_template_line_with_no_name_is_refused_before_anything_is_written(client):
    res = client.post(
        "/api/templates",
        json={"name": "Half a plan", "items": [{"title": "Pack", "subtasks": [{"title": "  "}]}]},
    )
    assert res.status_code == 400, res.text
    assert "step 1 needs a title" in res.json()["detail"]
    assert client.get("/api/templates").json()["templates"] == []


def test_the_export_carries_the_lines_the_rule_holds(client):
    """Rule 12: new persisted data is in the file, and a file from before it still imports."""
    rule = routine_line(client, routine(client), "Bottle")
    tick(client, rule, MON, rule["subtasks"][0]["id"])
    packed = pack(client, TODAY, "Passport", "Charger")

    document = client.get("/api/export").json()
    assert document["version"] == 5, "a file that can hold a routine's lines is a new version"
    assert document["schema_version"] == 8
    assert len(document["tables"]["routine_subtasks"]) == 1
    assert len(document["tables"]["blocks"]) == 3, "the lines travel in blocks"
    assert any(row["subtasks_done"] for row in document["tables"]["routine_overrides"]), (
        "the tick is a column on the day, and the day is in the file"
    )

    with store.db() as conn:
        for name in export.TABLES:
            conn.execute(f"DELETE FROM {name}")

    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 200, answer.text

    restored = next(
        r for r in client.get("/api/routines").json()["routines"] if r["id"] == rule["id"]
    )
    assert [s["title"] for s in restored["subtasks"]] == ["Bottle"]
    assert occurrence(client, restored, MON)["subtasks"][0]["done"] is True, (
        "the tick did not survive the file"
    )

    day = day_view(client)
    assert [s["title"] for s in found(client, TODAY, packed["id"])["subtasks"]] == [
        "Passport", "Charger"
    ]
    assert day["inbox"] == []


def test_a_file_written_before_checklists_still_imports(client):
    """What the format version is for: a version 4 file is whole, not partial.

    Built by taking a file written now and making it the file the release before this one would
    have written: version 4, no routine lines, and no line rows in `blocks` either — a file from
    before checklists cannot carry one.
    """
    routine_line(client, routine(client), "Bottle")
    pack(client, TODAY, "Passport")

    older = client.get("/api/export").json()
    older["version"] = 4
    del older["tables"]["routine_subtasks"]
    older["tables"]["blocks"] = [b for b in older["tables"]["blocks"] if b["parent_id"] is None]

    # The server's own reading of the file agrees it is complete rather than partial.
    assert export.check(older, 8)["routine_subtasks"] == []

    answer = client.post("/api/import", json={"confirm": "replace everything", "document": older})
    assert answer.status_code == 200, answer.text
    assert count("routine_subtasks") == 0
    assert client.get("/api/routines").json()["routines"][0]["subtasks"] == []
    assert day_view(client)["blocks"][0]["subtasks"] == [], "a line came from nowhere"


def test_a_file_whose_line_names_a_task_it_does_not_carry_is_refused(client):
    """The self-reference is checked, deferred or not, and the refusal says what is wrong."""
    packed = pack(client, TODAY, "Passport")
    document = client.get("/api/export").json()
    before = {name: count(name) for name in export.TABLES}

    document["tables"]["blocks"] = [b for b in document["tables"]["blocks"] if b["id"] != packed["id"]]

    answer = client.post(
        "/api/import", json={"confirm": "replace everything", "document": document}
    )
    assert answer.status_code == 400, "an orphaned line should be a refusal, not a 500"
    assert "contradicts itself" in answer.json()["detail"]
    assert {name: count(name) for name in export.TABLES} == before, (
        "a refused import left the lines behind"
    )
