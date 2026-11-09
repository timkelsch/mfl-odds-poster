"""Helpers for reading the MFL message board in the e2e test.

Pure functions are unit-tested in ``tests/unit/test_mfl_board.py``; the
network calls are only exercised by the e2e test itself.
"""
import datetime as dt
import re

import requests

import post

REQUEST_TIMEOUT_SECONDS = 10
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def as_list(value) -> list:
    """Normalize MFL JSON, which collapses one-element arrays to an object.

    Args:
        value: ``None``, a dict, or a list.

    Returns:
        list: Zero or more items.
    """
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalize_body(text: str) -> list[str]:
    """Reduce a post body to stripped, non-empty text lines.

    Args:
        text: Body with ``<br>`` and/or newline separators.

    Returns:
        list[str]: Lines for comparison.
    """
    lines = _BR.sub("\n", text).splitlines()
    return [line.strip() for line in lines if line.strip()]


def find_new_thread(threads: list[dict], subject: str, since: dt.datetime) -> dict | None:
    """Return the newest thread with ``subject`` last posted at or after ``since``.

    Args:
        threads: ``messageBoard.thread`` entries.
        subject: Expected subject.
        since: Test start time (timezone-aware).

    Returns:
        dict | None: The thread, or ``None`` if not there yet.
    """
    cutoff = since.timestamp()
    matches = [t for t in threads
               if t.get("subject") == subject and float(t.get("lastPostTime", 0)) >= cutoff]
    return max(matches, key=lambda t: float(t["lastPostTime"]), default=None)


def first_post(thread_export: dict) -> dict:
    """Extract franchise and body of a thread's opening post.

    Args:
        thread_export: JSON from ``TYPE=messageBoardThread``.

    Returns:
        dict: ``{"franchise": ..., "body": ...}``.

    Raises:
        AssertionError: If the export does not have the expected shape.
    """
    posts = as_list((thread_export.get("messageBoardThread") or {}).get("post"))
    assert posts, f"No messageBoardThread posts in export: {str(thread_export)[:300]}"
    opening = posts[0]
    return {"franchise": opening.get("franchise"), "body": opening.get("body", "")}


def in_season(day: dt.date) -> bool:
    """Whether the odds API should return games (Sep 1 to Feb 14).

    Args:
        day: Date to classify.

    Returns:
        bool: True during the NFL regular season and playoffs.
    """
    return day.month >= 9 or day.month == 1 or (day.month == 2 and day.day <= 14)


def expected_subject(now: dt.datetime) -> str:
    """Subject the poster should have used, from its own week math.

    Args:
        now: Time the gather lambda ran (UTC).

    Returns:
        str: e.g. ``"Week 10: Three-Leg Parlay"``.
    """
    week_1_start, _ = post.get_week_start_end(post.get_current_nfl_season_first_day())
    return f"Week {post.get_current_nfl_week(week_1_start, now)}: Three-Leg Parlay"


def export(host: str, cookie: str, params: dict) -> dict:
    """Call an authenticated MFL export.

    Args:
        host: League base URL, e.g. ``https://www46.myfantasyleague.com``.
        cookie: ``MFL_USER_ID`` value.
        params: Export query parameters (``TYPE``, ``L``...).

    Returns:
        dict: Parsed JSON.
    """
    response = requests.get(f"{host}/{post.YEAR}/export",
                            params={**params, "JSON": 1},
                            cookies={post.MFL_USER_COOKIE_KEY: cookie},
                            timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()
