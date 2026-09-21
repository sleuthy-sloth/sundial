"""Where a typed credential goes, and what is not allowed to go with it.

This module is the app's one front door for a secret, so the tests are mostly about the door
rather than the writing: which keys are accepted, what happens to a misspelled one, and whether
a value can smuggle a second entry into the file.

Nothing here touches a real credential file: both paths are pointed at a temporary directory,
and the round trip at the end proves the file is one the real reader will accept.
"""

from __future__ import annotations

import stat

import pytest

import caldav
import credentials
import env_file
import google_oauth


@pytest.fixture
def envs(tmp_path, monkeypatch):
    """Both files, in a temporary directory. Nothing in this module may touch a real one."""
    icloud = tmp_path / "icloud.env"
    google = tmp_path / "google.env"
    monkeypatch.setenv("SUNDIAL_ICLOUD_ENV", str(icloud))
    monkeypatch.setenv("SUNDIAL_GOOGLE_ENV", str(google))
    return icloud, google


ICLOUD = {"ICLOUD_USERNAME": "steve@example.com", "ICLOUD_APP_PASSWORD": "abcd-efgh-ijkl-mnop"}


# ------------------------------------------------------------------- the happy path


def test_what_is_written_is_a_file_the_real_reader_accepts(envs):
    """The point of the whole route: what the panel writes is what the sync reads."""
    icloud, _ = envs
    credentials.save("icloud", ICLOUD)

    loaded = caldav.load_credentials(icloud)
    assert loaded.username == "steve@example.com"
    assert loaded.password == "abcd-efgh-ijkl-mnop"


def test_the_file_is_0600_and_leaves_no_temporary_behind(envs):
    icloud, _ = envs
    credentials.save("icloud", ICLOUD)

    assert stat.S_IMODE(icloud.stat().st_mode) == 0o600
    assert [p.name for p in icloud.parent.iterdir()] == ["icloud.env"], "a .tmp file escaped"


def test_a_pasted_password_with_a_trailing_space_still_works(envs):
    """Copied from Apple's page, it arrives with a space or a newline on the end more often
    than not, and refusing that would be pedantry that reads as a wrong password."""
    icloud, _ = envs
    credentials.save("icloud", {**ICLOUD, "ICLOUD_APP_PASSWORD": " abcd-efgh-ijkl-mnop\n"})
    assert caldav.load_credentials(icloud).password == "abcd-efgh-ijkl-mnop"


def test_something_the_file_already_held_is_kept(envs):
    """A CalDAV server that is not iCloud is set in the file by hand, and typing a password
    must not be a way to lose it."""
    icloud, _ = envs
    icloud.write_text("ICLOUD_CALDAV_URL=https://dav.example.com/\n", encoding="utf-8")
    credentials.save("icloud", ICLOUD)

    assert env_file.read(icloud)["ICLOUD_CALDAV_URL"] == "https://dav.example.com/"
    assert caldav.load_credentials(icloud).endpoint == "https://dav.example.com/"


# ------------------------------------------------------------------- what is refused


def test_a_misspelled_key_is_refused_by_name_and_nothing_is_written(envs):
    icloud, _ = envs
    with pytest.raises(credentials.Refused) as caught:
        credentials.save("icloud", {"ICLOUD_USERNAME": "a@b.c", "ICLOUD_APP_PASWORD": "x"})

    assert "ICLOUD_APP_PASWORD" in str(caught.value)
    assert not icloud.exists(), "a refused request must not write half a file"


def test_a_blank_required_field_is_refused_in_words(envs):
    with pytest.raises(credentials.Refused) as caught:
        credentials.save("icloud", {**ICLOUD, "ICLOUD_APP_PASSWORD": "   "})
    assert "app-specific password" in str(caught.value)


def test_a_value_with_a_line_break_cannot_add_a_second_key(envs):
    """The file is one key per line, so a value that keeps a line break is not a value: it is
    a way to write an entry nobody asked for."""
    icloud, _ = envs
    with pytest.raises(credentials.Refused):
        credentials.save("icloud", {**ICLOUD, "ICLOUD_USERNAME": "a@b.c\nGOOGLE_REFRESH_TOKEN=stolen"})
    assert not icloud.exists()


def test_a_carriage_return_is_a_line_break_too(envs):
    with pytest.raises(credentials.Refused):
        credentials.save("icloud", {**ICLOUD, "ICLOUD_USERNAME": "a@b.c\rICLOUD_APP_PASSWORD="})


def test_an_unknown_provider_is_refused(envs):
    with pytest.raises(credentials.Refused) as caught:
        credentials.save("fastmail", ICLOUD)
    assert "fastmail" in str(caught.value)


# ------------------------------------------------------------------- google, which is not on


def test_the_refresh_token_is_not_a_thing_a_client_may_post(envs):
    """The callback owns it. A client that could post one could point sundial at somebody
    else's calendar."""
    _, google = envs
    with pytest.raises(credentials.Refused) as caught:
        credentials.save("google", {"GOOGLE_CLIENT_ID": "1.apps.googleusercontent.com",
                                    "GOOGLE_CLIENT_SECRET": "shh",
                                    "GOOGLE_REFRESH_TOKEN": "1//somebody-elses"})
    assert "GOOGLE_REFRESH_TOKEN" in str(caught.value)
    assert not google.exists()


def test_entering_a_client_id_again_does_not_log_anybody_out(envs):
    """Re-pasting the client secret is the commonest reason to come back to this form, and it
    must not throw away a working connection."""
    _, google = envs
    google_oauth.save(None, GOOGLE_CLIENT_ID="old.apps.googleusercontent.com",
                      GOOGLE_CLIENT_SECRET="old", GOOGLE_REFRESH_TOKEN="1//keep-me",
                      GOOGLE_ACCOUNT="steve@example.com")

    credentials.save("google", {"GOOGLE_CLIENT_ID": "new.apps.googleusercontent.com",
                                "GOOGLE_CLIENT_SECRET": "new"})

    after = google_oauth.load_configuration(None)
    assert after.client_id == "new.apps.googleusercontent.com"
    assert after.refresh_token == "1//keep-me", "the connection survived the edit"
    assert google_oauth.load_configuration(None).account == "steve@example.com"
