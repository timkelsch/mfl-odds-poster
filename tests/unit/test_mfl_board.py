"""Unit tests for the e2e message-board helpers."""
import datetime as dt

import pytest

from tests.e2e import mfl_board

UTC = dt.timezone.utc


@pytest.mark.parametrize("value, expected", [
    (None, []),
    ({"id": "1"}, [{"id": "1"}]),
    ([{"id": "1"}, {"id": "2"}], [{"id": "1"}, {"id": "2"}]),
])
def test_as_list_handles_mfl_single_element_quirk(value, expected) -> None:
    """MFL JSON collapses one-element arrays to a bare object."""
    assert mfl_board.as_list(value) == expected


def test_normalize_body_treats_br_and_newlines_alike() -> None:
    """The board may echo <br>, <br/> or newlines; compare on text lines."""
    assert mfl_board.normalize_body("<br>*** SUNDAY ***<br><br>A | -3.5 | 44.5<BR/>B<br />") == \
        mfl_board.normalize_body("\n*** SUNDAY ***\n\nA | -3.5 | 44.5\nB\n")
    assert mfl_board.normalize_body("x<br>y") != mfl_board.normalize_body("x<br>z")


def test_find_new_thread_picks_matching_subject_posted_after_start() -> None:
    """Old threads with the same subject (earlier CI runs) are ignored."""
    start = dt.datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    threads = [
        {"id": "1", "subject": "Week 10: Three-Leg Parlay", "lastPostTime": str(int(start.timestamp()) - 3600)},
        {"id": "2", "subject": "Trade talk", "lastPostTime": str(int(start.timestamp()) + 5)},
        {"id": "3", "subject": "Week 10: Three-Leg Parlay", "lastPostTime": str(int(start.timestamp()) + 5)},
    ]
    assert mfl_board.find_new_thread(threads, "Week 10: Three-Leg Parlay", start)["id"] == "3"
    assert mfl_board.find_new_thread(threads[:2], "Week 10: Three-Leg Parlay", start) is None


def test_first_post_reads_body_and_franchise() -> None:
    """The thread export's first post carries the poster's franchise and body."""
    export = {"messageBoardThread": {"post": {"id": "9", "franchise": "0008", "body": "A<br>B"}}}
    assert mfl_board.first_post(export) == {"franchise": "0008", "body": "A<br>B"}


def test_first_post_fails_clearly_on_unexpected_shape() -> None:
    """An unknown export shape must fail loudly, not pass vacuously."""
    with pytest.raises(AssertionError, match="messageBoardThread"):
        mfl_board.first_post({"error": {"$t": "nope"}})


@pytest.mark.parametrize("day, expected", [
    (dt.date(2026, 9, 9), True),
    (dt.date(2026, 12, 30), True),
    (dt.date(2027, 2, 3), True),
    (dt.date(2027, 2, 20), False),
    (dt.date(2027, 6, 1), False),
    (dt.date(2026, 8, 31), False),
])
def test_in_season(day: dt.date, expected: bool) -> None:
    """Non-empty odds are only required Sep through mid-Feb."""
    assert mfl_board.in_season(day) is expected


def test_expected_subject_matches_poster_week_math(monkeypatch: pytest.MonkeyPatch) -> None:
    """Subject uses the poster's own week computation."""
    import post
    monkeypatch.setattr(post, "get_current_nfl_season_first_day",
                        lambda: dt.datetime(2026, 9, 10, 7, tzinfo=UTC))
    assert mfl_board.expected_subject(dt.datetime(2026, 11, 11, 22, tzinfo=UTC)) == "Week 10: Three-Leg Parlay"
