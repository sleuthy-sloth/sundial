"""The card payload: what a phone is told about today.

Two things here are worth more than the rest. The card must satisfy the shape Cadu's validator
demands, because a wrong key is a retry at best and a card that never renders at worst — and
nothing local would have caught it. And `completed` must come from the block's own `done` flag
rather than from the clock: a card that ticks off a block merely because its hour has passed is
telling a comfortable lie about a day that did not happen, and no test downstream would notice.

Run with:  cd backend && .venv/bin/pytest -q
"""

import importlib.util
import pathlib
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("sundial_cadu_card", ROOT / "scripts" / "cadu_card.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)

DAY = "2026-09-21"


def block(block_id, title, start, minutes, done=False):
    return {
        "id": block_id, "title": title, "day": DAY, "start_min": start,
        "duration_min": minutes, "color": "slate", "notes": "", "done": done,
        "updated_at": "2026-09-21T00:00:00+00:00", "icon": "", "external_uid": None,
    }


def inbox_item(block_id, title, done=False):
    made = block(block_id, title, None, 30, done)
    made.update(day=None, start_min=None)
    return made


def document(blocks=(), inbox=(), day=DAY):
    return {"day": day, "today": DAY, "blocks": list(blocks), "inbox": list(inbox)}


def at(hour, minute=0):
    return datetime(2026, 9, 21, hour, minute)


# ---- the shaping helpers ------------------------------------------------------------------

def test_times_are_written_the_way_a_person_reads_a_clock():
    assert card.clock(0) == "00:00"
    assert card.clock(540) == "09:00"
    assert card.clock(1439) == "23:59"
    assert card.span(block("b", "x", 540, 90)) == "09:00–10:30"


def test_durations_read_as_durations():
    assert card.length(15) == "15m"
    assert card.length(60) == "1h"
    assert card.length(90) == "1h 30m"
    assert card.length(120) == "2h"


def test_today_is_called_today_and_other_days_are_dated():
    assert card.day_label(DAY, DAY) == "Today"
    assert card.day_label("2026-09-23", DAY) == "Wed 23 Sep"


# ---- the card -----------------------------------------------------------------------------

def test_the_card_says_what_is_now_and_what_is_next():
    seen = card.payload(
        document([block("a", "Write the thing", 540, 90), block("b", "Standup", 690, 15)]),
        at(9, 30),
    )
    assert seen["summary"].startswith("Now: Write the thing, until 10:30. Next: Standup at 11:30.")
    assert "does not change sundial" in seen["summary"], "the local-only tick has to be admitted"


def test_a_open_gap_reads_as_next_up_rather_than_now():
    seen = card.payload(document([block("a", "Standup", 690, 15)]), at(11, 0))
    assert seen["summary"].startswith("Next up: Standup at 11:30.")


def test_the_end_of_the_day_is_stated_rather_than_implied():
    seen = card.payload(document([block("a", "Standup", 690, 15)]), at(20, 0))
    assert "behind you" in seen["summary"]
    assert "ended at 11:45" in seen["summary"]


def test_an_empty_day_still_makes_a_card_that_renders():
    seen = card.payload(document(), at(9, 0))
    assert seen["checklist"]["items"] == []
    assert "Nothing planned" in seen["summary"]
    assert "no blocks" in seen["title"]


def test_items_keep_the_order_the_api_gave_them_and_the_inbox_follows():
    seen = card.payload(
        document([block("b", "Second", 690, 15), block("a", "First", 540, 90)],
                 [inbox_item("i", "Someday")]),
        at(9, 0),
    )
    items = seen["checklist"]["items"]
    # The API already sorts by start_min, so this asserts the order is *preserved* rather than
    # re-derived: a second sort is a second opinion about what "in order" means.
    assert [i["id"] for i in items] == ["b", "a", "i"]
    assert items[0]["detail"] == "11:30–11:45 · 15m"
    assert items[2]["detail"] == "anytime"


def test_done_comes_from_the_block_and_not_from_the_clock():
    # The block is over and still un-ticked. Ticking it here would be the card inventing a
    # finished day, and nothing would ever contradict it.
    seen = card.payload(document([block("a", "Over and un-ticked", 540, 90)]), at(20, 0))
    assert seen["checklist"]["items"][0]["completed"] is False

    seen = card.payload(document([block("a", "Ticked", 540, 90, done=True)]), at(1, 0))
    assert seen["checklist"]["items"][0]["completed"] is True, "done is believed whatever the hour"


def test_a_long_day_is_trimmed_and_the_summary_says_so():
    many = [block(f"b{n}", f"Block {n}", 60 * n, 30) for n in range(45)]
    seen = card.payload(document(many), at(9, 0))
    assert len(seen["checklist"]["items"]) == card.MAX_ITEMS
    assert "5 more did not fit" in seen["summary"]


# ---- the contract with Cadu's validator ----------------------------------------------------
# Written out rather than trusted to a reader: a wrong key fails validation with a terse
# sentence, and every one of these limits was a retry at some point.

def test_the_payload_has_exactly_the_keys_a_checklist_card_may_have():
    # `id` is in this set because the validator demanded it: an interactive card is refused
    # without one, and the error names the whole expected key list. Nothing local knew that.
    seen = card.payload(document([block("a", "x", 540, 30)]), at(9, 0))
    assert set(seen) == {"version", "type", "id", "title", "summary", "checklist"}
    assert seen["version"] == 1 and seen["type"] == "checklist"
    assert seen["id"] == "sundial-plan-2026-09-21"
    assert len(seen["id"]) <= 80
    assert set(seen["checklist"]) == {"items"}
    for item in seen["checklist"]["items"]:
        assert set(item) == {"id", "title", "detail", "completed"}
        assert isinstance(item["completed"], bool)
        assert all(isinstance(item[k], str) for k in ("id", "title", "detail"))


def test_the_payload_stays_inside_the_limits_the_validator_enforces():
    seen = card.payload(
        document([block("a", "x" * 300, 540, 30)], [inbox_item("i", "y" * 300)]), at(9, 0)
    )
    assert len(seen["title"]) <= 120
    assert len(seen["summary"]) <= 600
    for item in seen["checklist"]["items"]:
        assert len(item["title"]) <= 160, "an over-long title is a failed card, not a wrap"
        assert len(item["detail"]) <= 240
        assert len(item["id"]) <= 80
    ids = [item["id"] for item in seen["checklist"]["items"]]
    assert len(ids) == len(set(ids)), "ids have to be unique within the collection"


def test_the_card_id_is_stable_for_a_day_and_differs_between_days():
    # Stable, so re-rendering the same plan is the same card rather than a second one.
    one = card.payload(document([block("a", "x", 540, 30)]), at(9, 0))["id"]
    again = card.payload(document([block("a", "x", 540, 30)]), at(15, 0))["id"]
    other = card.payload(document([block("a", "x", 540, 30)], day="2026-09-22"), at(9, 0))["id"]
    assert one == again and one != other


def test_no_field_is_ever_null():
    # "Omit, never null" — a null fails the same string check a wrong type does.
    seen = card.payload(document([block("a", "x", 540, 30)], [inbox_item("i", "y")]), at(9, 0))
    assert all(value is not None for value in seen.values())
    for item in seen["checklist"]["items"]:
        assert all(value is not None for value in item.values())
