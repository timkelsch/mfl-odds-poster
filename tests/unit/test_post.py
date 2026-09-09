"""Unit tests for the post_odds lambda."""
import datetime as dt
import logging

import pytest
import requests

import post

UTC = dt.timezone.utc


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, payload: dict | None = None, status: int = 200,
                 text: str = "", cookies: dict | None = None) -> None:
        self._payload = payload or {}
        self.status_code = status
        self.text = text
        self.cookies = cookies or {}
        self.url = "https://example.test/"
        self.reason = "OK"

    def raise_for_status(self) -> None:
        """Mimic requests: raise on 4xx/5xx."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self) -> dict:
        """Return the canned payload."""
        return self._payload


@pytest.mark.parametrize("today, expected", [
    (dt.date(2026, 9, 9), 2026),
    (dt.date(2026, 12, 30), 2026),
    (dt.date(2027, 1, 15), 2026),
    (dt.date(2027, 2, 28), 2026),
    (dt.date(2027, 3, 1), 2027),
])
def test_get_season_year(today: dt.date, expected: int) -> None:
    """Jan/Feb belong to the previous season."""
    assert post.get_season_year(today) == expected


@pytest.mark.parametrize("season_year, expected", [
    (2024, dt.date(2024, 9, 5)),
    (2025, dt.date(2025, 9, 4)),
    (2026, dt.date(2026, 9, 10)),
    (2027, dt.date(2027, 9, 9)),
])
def test_get_default_season_first_day(season_year: int, expected: dt.date) -> None:
    """Kickoff is the Thursday after Labor Day."""
    kickoff = post.get_default_season_first_day(season_year)
    assert kickoff.date() == expected
    assert kickoff.weekday() == 3
    assert kickoff.tzinfo is UTC


def test_week_one_covers_wednesday_opener() -> None:
    """The 2026 Wednesday opener still lands in Week 1; later weeks count up."""
    week_1_start, _ = post.get_week_start_end(post.get_default_season_first_day(2026))
    assert week_1_start == dt.datetime(2026, 9, 8, tzinfo=UTC)
    opener = dt.datetime(2026, 9, 10, 0, 20, tzinfo=UTC)  # Wed Sep 9, 20:20 ET
    assert post.get_current_nfl_week(week_1_start, opener) == 1
    assert post.get_current_nfl_week(week_1_start, dt.datetime(2026, 9, 16, 22, tzinfo=UTC)) == 2
    assert post.get_current_nfl_week(week_1_start, dt.datetime(2027, 1, 6, 22, tzinfo=UTC)) == 18


def test_season_first_day_falls_back_when_api_forbidden(monkeypatch: pytest.MonkeyPatch,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    """A 403 (unsubscribed RapidAPI plan) must not break posting."""
    monkeypatch.setattr(post, "YEAR", 2026)

    def forbidden() -> dt.datetime:
        raise requests.HTTPError("403 Client Error: Forbidden")

    monkeypatch.setattr(post, "fetch_season_first_day_from_api", forbidden)
    with caplog.at_level(logging.WARNING):
        assert post.get_current_nfl_season_first_day().date() == dt.date(2026, 9, 10)
    assert "using computed kickoff" in caplog.text


def test_season_first_day_rejects_stale_api_season(monkeypatch: pytest.MonkeyPatch) -> None:
    """An API still serving last season (seen 2026-05-14) is ignored."""
    monkeypatch.setattr(post, "YEAR", 2026)
    monkeypatch.setattr(post, "fetch_season_first_day_from_api",
                        lambda: dt.datetime(2025, 9, 4, 7, tzinfo=UTC))
    assert post.get_current_nfl_season_first_day().date() == dt.date(2026, 9, 10)


def test_season_first_day_uses_api_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """A current-season API date wins over the computed one."""
    monkeypatch.setattr(post, "YEAR", 2026)
    api_date = dt.datetime(2026, 9, 9, 7, tzinfo=UTC)
    monkeypatch.setattr(post, "fetch_season_first_day_from_api", lambda: api_date)
    assert post.get_current_nfl_season_first_day() == api_date


def test_fetch_season_first_day_parses_week_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Week 1 start is read from the Regular Season section."""
    monkeypatch.setattr(post, "get_env_var", lambda _name: "secret")
    monkeypatch.setattr(post, "get_secret", lambda _arn, _key: "k")
    payload = {"sections": [
        {"label": "Preseason", "entries": [{"label": "Week 1", "startDate": "2026-08-06T07:00Z"}]},
        {"label": "Regular Season", "entries": [{"label": "Week 1", "startDate": "2026-09-09T07:00Z"}]},
    ]}
    monkeypatch.setattr(post.requests, "get", lambda *_a, **_k: _FakeResponse(payload))
    assert post.fetch_season_first_day_from_api() == dt.datetime(2026, 9, 9, 7, tzinfo=UTC)


def test_fetch_season_first_day_missing_week_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response without Week 1 raises instead of returning garbage."""
    monkeypatch.setattr(post, "get_env_var", lambda _name: "secret")
    monkeypatch.setattr(post, "get_secret", lambda _arn, _key: "k")
    monkeypatch.setattr(post.requests, "get",
                        lambda *_a, **_k: _FakeResponse({"sections": [{"label": "Regular Season", "entries": []}]}))
    with pytest.raises(ValueError):
        post.fetch_season_first_day_from_api()


def test_login_retries_until_cookie_and_never_logs_it(monkeypatch: pytest.MonkeyPatch,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    """A 200 without a cookie is a failed attempt; the cookie never hits the logs."""
    monkeypatch.setattr(post, "get_env_var", lambda _name: "secret")
    monkeypatch.setattr(post, "get_secret", lambda _arn, key: key)
    monkeypatch.setattr(post.time, "sleep", lambda _s: None)
    attempts = [
        _FakeResponse(status=200, text="<status>Bad password</status>"),
        _FakeResponse(status=200, cookies={"MFL_USER_ID": "s3cr3t-cookie"}),
    ]
    monkeypatch.setattr(post.requests, "post", lambda *_a, **_k: attempts.pop(0))
    with caplog.at_level(logging.INFO):
        assert post.login() == "s3cr3t-cookie"
    assert "s3cr3t-cookie" not in caplog.text


def test_login_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhausting retries raises rather than calling sys.exit."""
    monkeypatch.setattr(post, "get_env_var", lambda _name: "secret")
    monkeypatch.setattr(post, "get_secret", lambda _arn, key: key)
    monkeypatch.setattr(post.time, "sleep", lambda _s: None)
    monkeypatch.setattr(post.requests, "post", lambda *_a, **_k: _FakeResponse(status=500))
    with pytest.raises(RuntimeError, match="login failed"):
        post.login()


def test_get_host_reads_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The league export's baseURL is returned verbatim."""
    monkeypatch.setattr(post.requests, "get",
                        lambda *_a, **_k: _FakeResponse({"league": {"baseURL": "https://www46.example"}}))
    assert post.get_host() == "https://www46.example"


def test_get_host_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed export raises instead of returning None."""
    monkeypatch.setattr(post.requests, "get", lambda *_a, **_k: _FakeResponse(status=503))
    with pytest.raises(RuntimeError, match="Cannot obtain MFL API host"):
        post.get_host()


def test_post_rejected_by_mfl_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """MFL returns HTTP 200 with an XML error body; treat it as failure."""
    monkeypatch.setattr(post.time, "sleep", lambda _s: None)
    rejected = _FakeResponse(status=200, text='<?xml version="1.0"?>\n<error>Invalid League ID</error>')
    monkeypatch.setattr(post.requests, "get", lambda *_a, **_k: rejected)
    with pytest.raises(RuntimeError, match="Invalid League ID"):
        post.build_http_get_request("https://www46.example/2026/import", "cookie", {})


def test_post_success_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean 200 is returned to the caller."""
    ok = _FakeResponse(status=200, text='{"status": "OK"}')
    monkeypatch.setattr(post.requests, "get", lambda *_a, **_k: ok)
    assert post.build_http_get_request("https://www46.example/2026/import", "cookie", {}) is ok


def test_lambda_handler_requires_body() -> None:
    """A malformed event fails fast, before logging in."""
    with pytest.raises(ValueError):
        post.lambda_handler({"body": {}}, None)
