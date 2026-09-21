"""The sender, against a push service that records instead of delivering.

The tests that matter most are the ones about restraint: a block is announced once and not
sixty times, a moment of network trouble delays a notification rather than consuming it, and
a subscription the push service has forgotten is deleted rather than treated as a fault. The
wording is asserted too, because "nothing here sounds urgent" is a house rule and a house
rule that is not tested is a preference.

Run with:  cd backend && env -u PYTHONPATH .venv/bin/pytest -q
"""

import json
import os
import pathlib
import stat
import tempfile
from datetime import datetime

os.environ.setdefault("SUNDIAL_DB", str(pathlib.Path(tempfile.mkdtemp()) / "push-tests.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pywebpush import WebPushException  # noqa: E402

import app as sundial  # noqa: E402
import env_file  # noqa: E402
import push  # noqa: E402
from store import db  # noqa: E402

DAY = "2026-09-21"
GOOD = {
    "endpoint": "https://push.example/abc",
    "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
}


@pytest.fixture(autouse=True)
def fresh_db():
    sundial.DB_PATH.unlink(missing_ok=True)
    sundial.bootstrap()
    yield
    sundial.DB_PATH.unlink(missing_ok=True)


@pytest.fixture
def vapid_file(tmp_path, monkeypatch):
    """A throwaway VAPID identity, so no test touches the real one in the home directory."""
    target = tmp_path / "vapid.env"
    monkeypatch.setenv("SUNDIAL_VAPID_ENV", str(target))
    return target


@pytest.fixture
def identity(vapid_file):
    return push.load_vapid()


def add_block(title, day=DAY, start_min=540, duration_min=45, block_id="b1"):
    with db() as conn:
        conn.execute(
            """INSERT INTO blocks (id, title, day, start_min, duration_min, updated_at)
               VALUES (?, ?, ?, ?, ?, '2026-09-21T00:00:00')""",
            (block_id, title, day, start_min, duration_min),
        )


def subscribe(endpoint="https://push.example/abc"):
    with db() as conn:
        push.remember(conn, push.subscription({**GOOD, "endpoint": endpoint}))


class Recorder:
    """Stands in for pywebpush. Records what it was asked to send, and can be told to fail."""

    def __init__(self, *, raise_for=(), exc=None):
        self.calls = []
        self.raise_for = set(raise_for)
        self.exc = exc

    def __call__(self, **kwargs):
        endpoint = kwargs["subscription_info"]["endpoint"]
        self.calls.append(kwargs)
        if endpoint in self.raise_for:
            raise self.exc or WebPushException("gone")
        return "ok"

    @property
    def bodies(self):
        return [json.loads(call["data"]) for call in self.calls]


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


# --- the shape of a subscription ---------------------------------------------


def test_a_good_subscription_keeps_only_the_three_fields_a_push_service_needs():
    sub = push.subscription({**GOOD, "expirationTime": 123, "keys": {**GOOD["keys"], "extra": "x"}})
    assert sub == {
        "endpoint": "https://push.example/abc",
        "p256dh": "p256dh-value",
        "auth": "auth-value",
    }


@pytest.mark.parametrize("missing", ["endpoint", "keys"])
def test_a_subscription_missing_its_parts_is_refused_by_name(missing):
    body = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(ValueError):
        push.subscription(body)


@pytest.mark.parametrize("key", ["p256dh", "auth"])
def test_a_key_left_out_of_the_keys_object_is_refused(key):
    body = {**GOOD, "keys": {k: v for k, v in GOOD["keys"].items() if k != key}}
    with pytest.raises(ValueError) as err:
        push.subscription(body)
    assert key in str(err.value)


def test_a_value_with_a_line_break_is_refused():
    # The file-shaped rule, applied to a row: a value that can contain a newline is not a
    # value, it is a way to write fields nobody asked for.
    with pytest.raises(ValueError):
        push.subscription({**GOOD, "endpoint": "https://push.example/ab\nc"})


def test_an_endpoint_that_is_not_https_is_refused():
    with pytest.raises(ValueError):
        push.subscription({**GOOD, "endpoint": "http://push.example/abc"})


# --- the subscription table ---------------------------------------------------


def test_resubscribing_the_same_browser_updates_rather_than_doubles():
    subscribe()
    with db() as conn:
        push.remember(conn, {"endpoint": GOOD["endpoint"], "p256dh": "new", "auth": "new"})
        rows = conn.execute("SELECT p256dh FROM push_subscriptions").fetchall()
    assert len(rows) == 1
    assert rows[0]["p256dh"] == "new"


def test_forgetting_an_unknown_endpoint_is_zero_rows_not_an_error():
    with db() as conn:
        assert push.forget(conn, "https://push.example/never-seen") == 0


# --- what is due --------------------------------------------------------------


def test_a_block_starting_now_is_due():
    add_block("Standup", start_min=540)
    with db() as conn:
        assert [b["title"] for b in push.due(conn, datetime(2026, 9, 21, 9, 0))] == ["Standup"]


def test_a_block_that_started_a_minute_ago_is_still_worth_saying():
    # Ticks are not punctual, and being late by a minute is not a reason to stay silent.
    add_block("Standup", start_min=540)
    with db() as conn:
        assert len(push.due(conn, datetime(2026, 9, 21, 9, 1))) == 1


def test_a_block_that_started_before_the_grace_window_is_history():
    # The load-bearing bound: start the app after a weekend and nothing from the weekend
    # should arrive as a notification.
    add_block("Standup", start_min=540)
    with db() as conn:
        assert push.due(conn, datetime(2026, 9, 21, 9, push.GRACE_MIN + 1)) == []


def test_a_block_that_has_not_started_yet_is_not_due():
    add_block("Standup", start_min=545)
    with db() as conn:
        assert push.due(conn, datetime(2026, 9, 21, 9, 0)) == []


def test_an_inbox_block_is_never_due():
    # No day and no start: there is no hour at which it begins, so there is nothing to say.
    add_block("Someday", day=None, start_min=None)
    with db() as conn:
        assert push.due(conn, datetime(2026, 9, 21, 9, 0)) == []


def test_a_block_on_another_day_is_not_due():
    add_block("Standup", day="2026-09-22", start_min=540)
    with db() as conn:
        assert push.due(conn, datetime(2026, 9, 21, 9, 0)) == []


def test_a_block_already_announced_is_not_due_again():
    add_block("Standup", start_min=540)
    with db() as conn:
        conn.execute(
            "INSERT INTO push_sent (block_id, day, sent_at) VALUES ('b1', ?, 'x')", (DAY,)
        )
        assert push.due(conn, datetime(2026, 9, 21, 9, 0)) == []


def test_the_same_block_is_due_again_the_next_day():
    # A repeat is a different day, not a different block, and the key says so.
    add_block("Standup", day="2026-09-22", start_min=540)
    with db() as conn:
        conn.execute(
            "INSERT INTO push_sent (block_id, day, sent_at) VALUES ('b1', ?, 'x')", (DAY,)
        )
        assert len(push.due(conn, datetime(2026, 9, 22, 9, 0))) == 1


# --- the words ----------------------------------------------------------------


def test_the_payload_is_the_block_title_and_its_span():
    assert push.payload({"id": "b1", "title": "Standup", "start_min": 540, "duration_min": 45}) == {
        "title": "Standup",
        "body": "09:00 · 45 min",
        "tag": "sundial-b1",
    }


def test_the_tag_is_the_block_so_a_second_notification_replaces_the_first():
    first = push.payload({"id": "b1", "title": "A", "start_min": 540})
    second = push.payload({"id": "b1", "title": "B", "start_min": 540})
    assert first["tag"] == second["tag"]


@pytest.mark.parametrize(
    "minutes,spoken",
    [(5, "5 min"), (45, "45 min"), (60, "1 h"), (90, "1 h 30 min"), (1440, "24 h")],
)
def test_a_length_is_spoken_the_way_a_person_would(minutes, spoken):
    assert push.spoken_length(minutes) == spoken


def test_a_block_with_no_length_still_reads_as_a_time():
    assert push.payload({"id": "b1", "title": "A", "start_min": 0})["body"] == "00:00"


@pytest.mark.parametrize("word", ["now", "late", "overdue", "hurry", "remaining", "missed"])
def test_nothing_in_the_words_sounds_urgent(word):
    body = push.payload({"id": "b1", "title": "Standup", "start_min": 540, "duration_min": 45})
    assert word not in (body["title"] + " " + body["body"]).lower()


# --- the tick -----------------------------------------------------------------


def test_a_tick_announces_a_due_block_once_and_remembers_it(identity):
    add_block("Standup", start_min=540)
    subscribe()
    recorder = Recorder()

    with db() as conn:
        first = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)

    assert first["due"] == 1
    assert first["sent"] == 1
    assert recorder.bodies == [{"title": "Standup", "body": "09:00 · 45 min", "tag": "sundial-b1"}]

    with db() as conn:
        second = push.tick(
            conn, datetime(2026, 9, 21, 9, 1), identity=identity, pusher=recorder
        )
    assert second["due"] == 0
    assert second["sent"] == 0
    assert len(recorder.calls) == 1, "the same block must not be announced twice"


def test_the_tick_speaks_to_every_subscriber(identity):
    add_block("Standup", start_min=540)
    subscribe("https://push.example/phone")
    subscribe("https://push.example/laptop")
    recorder = Recorder()

    with db() as conn:
        summary = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)

    assert summary["sent"] == 1
    assert sorted(c["subscription_info"]["endpoint"] for c in recorder.calls) == [
        "https://push.example/laptop",
        "https://push.example/phone",
    ]


def test_with_no_subscribers_nothing_is_announced_and_nothing_is_recorded(identity):
    # Subscribing later must not have cost you this morning: the block is left unannounced
    # rather than consumed by a tick that had nobody to tell.
    add_block("Standup", start_min=540)
    recorder = Recorder()
    with db() as conn:
        summary = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)
        assert summary["sent"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM push_sent").fetchone()["n"] == 0

    subscribe()
    with db() as conn:
        again = push.tick(conn, datetime(2026, 9, 21, 9, 1), identity=identity, pusher=recorder)
    assert again["sent"] == 1


def test_a_subscription_the_service_has_forgotten_is_deleted_not_retried(identity):
    add_block("Standup", start_min=540)
    subscribe()
    recorder = Recorder(
        raise_for=["https://push.example/abc"], exc=WebPushException("gone", Response(410))
    )

    with db() as conn:
        summary = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)
        left = conn.execute("SELECT COUNT(*) AS n FROM push_sent").fetchone()["n"]

    assert summary["expired"] == ["https://push.example/abc"]
    assert summary["sent"] == 0
    assert left == 0, "a subscription that is over is not the block having been announced"
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()["n"] == 0


@pytest.mark.parametrize("status", [404, 410])
def test_both_answers_that_mean_over_are_read_from_wherever_they_arrived(identity, status):
    add_block("Standup", start_min=540)
    subscribe()
    recorder = Recorder(raise_for=["https://push.example/abc"], exc=WebPushException("x", Response(status)))
    with db() as conn:
        assert push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)["expired"]


def test_a_transport_error_delays_a_notification_rather_than_consuming_it(identity):
    # 503 is the push service having a bad minute, not the subscription being over.
    add_block("Standup", start_min=540)
    subscribe()
    failing = Recorder(
        raise_for=["https://push.example/abc"], exc=WebPushException("busy", Response(503))
    )

    with db() as conn:
        summary = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=failing)
        assert summary["sent"] == 0
        assert summary["failed"]
        assert conn.execute("SELECT COUNT(*) AS n FROM push_sent").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()["n"] == 1

    working = Recorder()
    with db() as conn:
        retried = push.tick(conn, datetime(2026, 9, 21, 9, 2), identity=identity, pusher=working)
    assert retried["sent"] == 1


def test_one_live_subscriber_is_enough_to_count_as_announced(identity):
    add_block("Standup", start_min=540)
    subscribe("https://push.example/dead")
    subscribe("https://push.example/live")
    recorder = Recorder(
        raise_for=["https://push.example/dead"], exc=WebPushException("busy", Response(503))
    )
    with db() as conn:
        summary = push.tick(conn, datetime(2026, 9, 21, 9, 0), identity=identity, pusher=recorder)
    assert summary["sent"] == 1


# --- the identity -------------------------------------------------------------


def test_the_identity_is_made_once_and_kept_private(vapid_file):
    first = push.public_key()
    assert vapid_file.exists()
    assert stat.S_IMODE(vapid_file.stat().st_mode) == 0o600
    assert push.public_key() == first, "a second ask must not mint a second identity"
    values = env_file.read(vapid_file)
    assert set(values) == {"VAPID_PRIVATE_KEY"}
    assert "\n" not in values["VAPID_PRIVATE_KEY"], "the value is one line"


def test_a_corrupt_identity_file_is_replaced_rather_than_fatal(vapid_file):
    vapid_file.write_text("VAPID_PRIVATE_KEY=not-a-key\n")
    assert push.public_key(), "a new identity is made rather than refusing to start"
    assert push.public_key().startswith("B")


# --- the endpoints ----------------------------------------------------------
#
# A client built without a context manager, so the lifespan never runs and the minute tick
# stays out of the tests. The tick has its own tests, above, against a recorder.


@pytest.fixture
def client():
    return TestClient(sundial.app)


def test_the_key_endpoint_hands_over_an_identity_the_browser_can_use(client, vapid_file):
    body = client.get("/api/push/key").json()
    assert body["public_key"].startswith("B")
    assert len(body["public_key"]) == 87, "an uncompressed P-256 point, base64url, unpadded"
    assert body["subscribers"] == 0


def test_subscribing_keeps_it_and_says_how_many_have(client):
    res = client.post("/api/push/subscribe", json=GOOD)
    assert res.status_code == 201, res.text
    assert res.json()["subscribers"] == 1
    assert client.get("/api/push/key").json()["subscribers"] == 1


def test_resubscribing_the_same_browser_does_not_double_the_count(client):
    client.post("/api/push/subscribe", json=GOOD)
    client.post("/api/push/subscribe", json=GOOD)
    assert client.get("/api/push/key").json()["subscribers"] == 1


def test_a_malformed_subscription_is_refused_with_the_reason(client):
    # Both refusals reach the caller with the reason rather than a bare 400, because the
    # settings panel is where this gets read.
    missing = client.post("/api/push/subscribe", json={"endpoint": GOOD["endpoint"]})
    assert missing.status_code == 400
    assert "p256dh" in missing.json()["detail"]

    scheme = client.post(
        "/api/push/subscribe", json={**GOOD, "endpoint": "http://not-https.example/x"}
    )
    assert scheme.status_code == 400
    assert "https" in scheme.json()["detail"]


def test_unsubscribing_removes_it(client):
    client.post("/api/push/subscribe", json=GOOD)
    body = client.post("/api/push/unsubscribe", json={"endpoint": GOOD["endpoint"]}).json()
    assert body == {"removed": True, "subscribers": 0}


def test_unsubscribing_something_never_subscribed_is_not_an_error(client):
    # A browser that clears its own state calls this too, and being told off for tidying up
    # after yourself is the wrong answer.
    res = client.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/gone"})
    assert res.status_code == 200
    assert res.json() == {"removed": False, "subscribers": 0}


def test_the_test_button_admits_when_nobody_is_subscribed(client):
    # It must not claim to have sent something. "Sent to nobody" and "sent" are different
    # answers and the panel shows them differently.
    body = client.post("/api/push/test").json()
    assert body["subscribers"] == 0
    assert body["sent"] == 0


def test_the_default_subject_is_a_domain_a_push_service_will_believe():
    # Apple answers 403 BadJwtToken for `mailto:sundial@localhost`. Nothing local exposes that,
    # so the guard has to be on the value itself: a reserved name is not a domain a push
    # service will accept as a way to reach the operator.
    assert push.DEFAULT_SUBJECT.startswith("mailto:")
    domain = push.DEFAULT_SUBJECT.split("@", 1)[1]
    assert "localhost" not in domain and "." in domain, push.DEFAULT_SUBJECT


def test_the_subject_can_be_overridden_for_a_real_deployment(monkeypatch):
    monkeypatch.setenv("SUNDIAL_VAPID_SUBJECT", "mailto:someone@real.example")
    assert push.subject_claim() == "mailto:someone@real.example"


def test_the_identity_lives_beside_the_calendar_credentials():
    # One directory holds the files a deployment must not commit. This file is one of them,
    # and a second directory to remember would be a second directory to get wrong.
    root = pathlib.Path(push.__file__).resolve().parent.parent
    assert push.DEFAULT_VAPID.parent == root
    assert push.DEFAULT_VAPID.name == "vapid.env"


def test_and_the_ignore_rule_moves_with_it():
    # The app writes this file by itself, so it can never be a file someone remembers to add
    # to the ignore list by hand. If the location ever changes, this fails with it.
    root = pathlib.Path(push.__file__).resolve().parent.parent
    assert "vapid.env" in (root / ".gitignore").read_text()
