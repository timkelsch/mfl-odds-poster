"""Unit tests for the gather_odds lambda."""
import logging
from datetime import datetime

import pytest
import pytz

import gather

PT = pytz.timezone("US/Pacific")
NOW = PT.localize(datetime(2026, 9, 9, 12, 0))  # Wednesday of 2026 NFL Week 1


def _game(away: str, home: str, commence_utc: str, spread_team: str | None = None,
          spread: float = -3.5, total: float = 44.5, order: tuple = ("spreads", "totals"),
          bookmakers: bool = True) -> dict:
    """Build a the-odds-api game. ``spread_team=None`` makes a pick'em."""
    if spread_team is None:
        outcomes = [{"name": away, "point": 0.0}, {"name": home, "point": 0.0}]
    else:
        other = home if spread_team == away else away
        outcomes = [{"name": spread_team, "point": spread}, {"name": other, "point": -spread}]
    markets = {
        "spreads": {"key": "spreads", "outcomes": outcomes},
        "totals": {"key": "totals", "outcomes": [
            {"name": "Over", "point": total}, {"name": "Under", "point": total}]},
    }
    return {
        "commence_time": commence_utc,
        "away_team": away,
        "home_team": home,
        "bookmakers": [{"key": "draftkings", "markets": [markets[k] for k in order]}] if bookmakers else [],
    }


def test_transform_filters_to_current_week_and_sorts() -> None:
    """Only Tue Sep 8 .. Mon Sep 14 (PT) games survive, in kickoff order."""
    games = gather.adjust_times_zones([
        _game("Denver Broncos", "Kansas City Chiefs", "2026-09-15T00:15:00Z", "Kansas City Chiefs", -2.5, 43.5),
        _game("New England Patriots", "Seattle Seahawks", "2026-09-10T00:20:00Z", "Seattle Seahawks", -3.5, 44.5),
        _game("Too Early", "Last Week", "2026-09-07T20:00:00Z", "Last Week"),
        _game("Too Late", "Next Week", "2026-09-17T00:15:00Z", "Next Week"),
    ])
    result = gather.transform_game_data(games, now=NOW)
    assert [g["home_team"] for g in result] == ["Seattle Seahawks", "Kansas City Chiefs"]
    assert result[0] == {
        "commence_time": "2026-09-09T17:20:00-07:00",
        "favored_team": "Seattle Seahawks",
        "away_team": "New England Patriots",
        "home_team": "Seattle Seahawks",
        "point_spread": -3.5,
        "totals_point": 44.5,
    }


def test_transform_handles_pickem_as_home_minus_half() -> None:
    """No negative spread: home team is favored and the line becomes -0.5."""
    games = gather.adjust_times_zones([_game("Away", "Home", "2026-09-13T17:00:00Z")])
    result = gather.transform_game_data(games, now=NOW)
    assert result[0]["favored_team"] == "Home"
    assert result[0]["point_spread"] == -0.5


def test_transform_skips_games_without_bookmaker(caplog: pytest.LogCaptureFixture) -> None:
    """A game DraftKings has not priced yet is skipped, not fatal."""
    games = gather.adjust_times_zones([
        _game("Unpriced", "Game", "2026-09-13T17:00:00Z", bookmakers=False),
        _game("Away", "Home", "2026-09-13T20:00:00Z", "Away", -7.0, 50.0),
    ])
    with caplog.at_level(logging.WARNING):
        result = gather.transform_game_data(games, now=NOW)
    assert [g["away_team"] for g in result] == ["Away"]
    assert "Skipping Unpriced @ Game" in caplog.text


def test_transform_does_not_depend_on_market_order() -> None:
    """Markets are looked up by key, not position."""
    games = gather.adjust_times_zones([
        _game("Away", "Home", "2026-09-13T17:00:00Z", "Away", -7.0, 50.0, order=("totals", "spreads")),
    ])
    result = gather.transform_game_data(games, now=NOW)
    assert result[0]["point_spread"] == -7.5
    assert result[0]["totals_point"] == 50.5


@pytest.mark.parametrize("value, expected", [
    (3.0, 3.5),
    (-3.0, -3.5),
    (44, 44.5),      # JSON int, has no is_integer() on Python 3.11
    (2.5, 2.5),
    (-6.5, -6.5),
    (0.0, -0.5),
])
def test_adjust_float(value: float, expected: float) -> None:
    """Whole numbers move half a point away from zero; halves are untouched."""
    assert gather.adjust_float(value) == expected


def test_format_games_groups_by_day_and_marks_favorite() -> None:
    """Favored team carries the line; day headers appear once per day."""
    games = gather.adjust_times_zones([
        _game("New England Patriots", "Seattle Seahawks", "2026-09-10T00:20:00Z", "Seattle Seahawks", -3.5, 44.5),
        _game("Dallas Cowboys", "New York Giants", "2026-09-13T17:00:00Z", "Dallas Cowboys", -3.5, 48.5),
        _game("Atlanta Falcons", "Pittsburgh Steelers", "2026-09-13T17:00:00Z", "Pittsburgh Steelers", -3.5, 42.5),
    ])
    text = gather.format_games(gather.transform_game_data(games, now=NOW), "\n")
    assert text.count("*** WEDNESDAY ***") == 1
    assert text.count("*** SUNDAY ***") == 1
    assert "New England Patriots\nSeattle Seahawks | -3.5 | 44.5\n" in text
    assert "Dallas Cowboys | -3.5 | 48.5\nNew York Giants\n" in text


def test_main_with_local_source_needs_no_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI path reads a file and never touches SSM."""
    monkeypatch.delenv("CONFIG_PARAMETER_NAME", raising=False)
    source = tmp_path / "games.json"
    source.write_text('[{"commence_time": "2026-09-13T17:00:00Z", "away_team": "Away", "home_team": "Home", '
                      '"bookmakers": [{"key": "draftkings", "markets": ['
                      '{"key": "spreads", "outcomes": [{"name": "Away", "point": -3.5}, '
                      '{"name": "Home", "point": 3.5}]}, '
                      '{"key": "totals", "outcomes": [{"name": "Over", "point": 41.5}]}]}]}]', encoding="utf-8")

    class _FixedDatetime(datetime):
        """datetime whose now() is pinned to Week 1 Wednesday."""

        @classmethod
        def now(cls, tz=None):  # noqa: D102 - mirrors datetime.now
            return NOW.astimezone(tz) if tz else NOW

    monkeypatch.setattr(gather, "datetime", _FixedDatetime)
    body = gather.main("\n", str(source))["body"]
    assert "Away | -3.5 | 41.5" in body


def test_get_config_reads_decrypted_ssm_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The odds API key comes from the SecureString named in CONFIG_PARAMETER_NAME."""
    calls: list = []

    class _FakeSsm:
        def get_parameter(self, **kwargs) -> dict:
            calls.append(kwargs)
            return {"Parameter": {"Value": '{"the-odds-api-key": "abc"}'}}

    monkeypatch.setenv("CONFIG_PARAMETER_NAME", "/mfl-odds")
    monkeypatch.setattr(gather.boto3, "client", lambda service: _FakeSsm())
    assert gather.get_config("the-odds-api-key") == "abc"
    assert calls == [{"Name": "/mfl-odds", "WithDecryption": True}]
