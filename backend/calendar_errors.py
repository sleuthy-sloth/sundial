"""The errors a calendar transport may raise, named once so two transports can share them.

A transport's job is to turn a remote server's behaviour into something a person can act
on: nothing configured yet, this needs reconnecting, this server refused. The engine stores
those messages in `calendars.last_error` and the interface shows them, so none of them may
ever carry a credential — a token or a password that leaks in here is a credential in a
database, a log file and a screenshot of the rail.

They live in their own module because CalDAV is no longer the only transport: a Google
error is not a CalDAV error, and importing one transport's module to describe the other
transport's failure is how the two become one.
"""

from __future__ import annotations


class CalendarError(Exception):
    """Something a person can act on. Never carries a credential."""


class NotConfigured(CalendarError):
    """No usable credentials yet. A normal state, not a failure: it is what a fresh
    install looks like, and the answer is a sentence about what to create."""


class Reconnect(CalendarError):
    """The credentials existed and the server no longer accepts them.

    Its own class rather than a message, because the difference matters to the interface:
    a refused credential is not a server being down, and the fix is a person clicking
    something rather than waiting. Google makes this routine — see google_oauth.py — so the
    rail needs to be able to say "reconnect" instead of showing a stack of network text.
    """
