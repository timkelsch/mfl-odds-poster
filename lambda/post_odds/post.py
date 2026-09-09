"""Post the weekly NFL odds summary to the MyFantasyLeague message board."""
import datetime
import json
import logging
import os
import time

import boto3
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_RETRIES = 3
SLEEP_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 5
MFL_API_HOST = "https://api.myfantasyleague.com"
ENV_VAR_SECRET_ARN = "SECRET_ARN"
# checkov:skip=CKV_SECRET_6: not a secret
NFL_API_URL = "https://nfl-football-api.p.rapidapi.com/nfl-whitelist"
NFL_API_HOST = "nfl-football-api.p.rapidapi.com"
SUBSECRET_KEY_NFL_API_API_KEY = "nfl-api-key"

MFL_USER_COOKIE_KEY = "MFL_USER_ID"
REQUEST_TYPE = "messageBoard"
API = "import"
LEAGUE_ID = "15781"
FRANCHISE_ID = "0008"
THREAD = ""  # "6480193" == test thread


def get_season_year(today: datetime.date | None = None) -> int:
    """Return the NFL season year for a date.

    January and February (playoffs, Super Bowl) belong to the season that
    started the previous autumn, and MFL keys leagues by that season year.

    Args:
        today: Date to evaluate. Defaults to the current local date.

    Returns:
        int: Season year.
    """
    today = today or datetime.date.today()
    return today.year - 1 if today.month < 3 else today.year


YEAR = get_season_year()


def lambda_handler(event: dict, _context: object) -> dict:
    """Log in to MFL and post the odds body carried in the event.

    Args:
        event: Payload from the gather lambda, ``{"body": {"body": "<html>"}}``.
        _context: Lambda context (unused).

    Returns:
        dict: ``statusCode`` and the MFL response text.

    Raises:
        ValueError: If the event does not carry an odds body.
        RuntimeError: If MFL login, host lookup, or the post itself fails.
    """
    try:
        body = event["body"]["body"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Event is missing ['body']['body'] from the gather lambda") from exc

    cookie = login()
    host = get_host()

    first_day_regular_season = get_current_nfl_season_first_day()
    week_1_start_date, _ = get_week_start_end(first_day_regular_season)
    week = get_current_nfl_week(week_1_start_date, datetime.datetime.now(datetime.timezone.utc))
    subject = f"Week {week}: Three-Leg Parlay"
    logger.info("subject: %s", subject)

    query_object = build_query_object(REQUEST_TYPE, LEAGUE_ID, FRANCHISE_ID, THREAD, subject, body)
    response = build_http_get_request(f"{host}/{YEAR}/{API}", cookie, query_object)
    return {"statusCode": response.status_code, "body": response.text}


def get_current_nfl_week(first_game_date: datetime.datetime, input_date: datetime.datetime) -> int:
    """Calculate the NFL week number for a date.

    Args:
        first_game_date: Start of Week 1 (already normalized to its Tuesday).
        input_date: Date to classify.

    Returns:
        int: NFL week number, 1-based.
    """
    days_since_first_game = (input_date - first_game_date).days
    logger.info("days_since_first_game: %s", days_since_first_game)
    return days_since_first_game // 7 + 1


def get_default_season_first_day(season_year: int) -> datetime.datetime:
    """Compute the regular-season kickoff without any external API.

    Since 2002 the NFL has opened on the Thursday after Labor Day (the first
    Monday of September). Occasional Wednesday openers (e.g. 2026) still fall
    inside the same Tuesday-anchored Week 1 window.

    Args:
        season_year: NFL season year.

    Returns:
        datetime.datetime: Kickoff Thursday at 07:00 UTC (midnight Pacific).
    """
    sept_first = datetime.date(season_year, 9, 1)
    labor_day = sept_first + datetime.timedelta(days=(7 - sept_first.weekday()) % 7)
    kickoff = labor_day + datetime.timedelta(days=3)
    return datetime.datetime(kickoff.year, kickoff.month, kickoff.day, 7, tzinfo=datetime.timezone.utc)


def fetch_season_first_day_from_api() -> datetime.datetime:
    """Fetch the regular-season Week 1 start date from the RapidAPI NFL schedule.

    Returns:
        datetime.datetime: Week 1 start date, timezone-aware.

    Raises:
        requests.RequestException: On network errors or non-2xx responses
            (403 means the RapidAPI subscription is inactive).
        ValueError: If the body is not JSON or lacks a Regular Season / Week 1 entry.
    """
    secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
    api_key = get_secret(secret_arn, SUBSECRET_KEY_NFL_API_API_KEY)
    headers = {"rapidapi-host": NFL_API_HOST, "rapidapi-key": api_key}
    response = requests.get(NFL_API_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    for section in data.get("sections", []):
        if section.get("label") != "Regular Season":
            continue
        for entry in section.get("entries", []):
            if entry.get("label") == "Week 1":
                return datetime.datetime.fromisoformat(entry["startDate"])
    raise ValueError("NFL schedule API response has no Regular Season / Week 1 entry")


def get_current_nfl_season_first_day() -> datetime.datetime:
    """Return the current season's Week 1 start, preferring the schedule API.

    Falls back to the computed Labor Day rule when the API is unreachable,
    unsubscribed, malformed, or still serving a previous season.

    Returns:
        datetime.datetime: Week 1 start date, timezone-aware.
    """
    fallback = get_default_season_first_day(YEAR)
    try:
        api_date = fetch_season_first_day_from_api()
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning("NFL schedule API unavailable (%s); using computed kickoff %s", exc, fallback.date())
        return fallback
    if api_date.year != YEAR:
        logger.warning("NFL schedule API returned %s for season %s; using computed kickoff %s",
                       api_date.date(), YEAR, fallback.date())
        return fallback
    logger.info("datetime_startDate: %s", api_date)
    return api_date


def get_week_start_end(date: datetime.datetime,
                       week_start: int = 1) -> tuple[datetime.datetime, datetime.datetime]:
    """Return the bounds of the NFL week containing ``date``.

    Weeks are anchored on Tuesday (``week_start=1``) in whatever timezone
    ``date`` carries. Only the start is used, to derive the week number.

    Args:
        date: Any datetime inside the week.
        week_start: ``datetime.weekday()`` value that begins a week (0=Monday).

    Returns:
        tuple[datetime.datetime, datetime.datetime]: Week start (00:00) and end (23:59:59).
    """
    while date.weekday() != week_start:
        date -= datetime.timedelta(days=1)

    week_start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_date = (week_start_date + datetime.timedelta(days=6)
                     ).replace(hour=23, minute=59, second=59, microsecond=999)

    return week_start_date, week_end_date


def build_query_object(request_type: str, league_id: str, franchise_id: str,
                       thread: str, subject: str, body: str) -> dict:
    """Build the MFL ``import`` query parameters for a message-board post.

    Args:
        request_type: MFL import TYPE, e.g. ``messageBoard``.
        league_id: MFL league id.
        franchise_id: Posting franchise id.
        thread: Existing thread id, or empty string for a new thread.
        subject: Post subject.
        body: Post body (HTML ``<br>`` line breaks).

    Returns:
        dict: Query parameters.
    """
    return {
        "TYPE": request_type,
        "L": league_id,
        "FRANCHISE_ID": franchise_id,
        "THREAD": thread,
        "SUBJECT": subject,
        "BODY": body,
        "JSON": 1
    }


def get_secret(secret_name: str, subsecret_key: str) -> str:
    """Retrieve one key from a JSON secret in AWS Secrets Manager.

    Args:
        secret_name: Secret name or ARN.
        subsecret_key: Key inside the JSON secret string.

    Returns:
        str: The secret value. Never log it.

    Raises:
        ValueError: If ``secret_name`` is empty.
        botocore.exceptions.ClientError: If the secret cannot be read.
        KeyError: If ``subsecret_key`` is not in the secret.
    """
    if not secret_name:
        raise ValueError("Secret name must be provided.")
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    secret_data = json.loads(response["SecretString"])
    return secret_data[subsecret_key]


def get_env_var(var_name: str) -> str:
    """Read a required environment variable.

    Args:
        var_name: Variable name.

    Returns:
        str: Variable value.

    Raises:
        KeyError: If the variable is not set.
    """
    value = os.environ.get(var_name)
    if value is None:
        raise KeyError(f"Required environment variable {var_name} is not set")
    return value


def login() -> str:
    """Log in to MFL and return the session cookie value.

    Returns:
        str: ``MFL_USER_ID`` cookie value. Never log it.

    Raises:
        RuntimeError: If no attempt yields a 200 with a session cookie.
    """
    secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
    username = get_secret(secret_arn, "mfl-username")
    password = get_secret(secret_arn, "mfl-password")

    url = f"{MFL_API_HOST}/{YEAR}/login?"
    data = {"USERNAME": username, "PASSWORD": password, "XML": 1}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(url, headers=headers, data=data, timeout=REQUEST_TIMEOUT_SECONDS)
        # Do not log the response body or cookies: they carry the session credential.
        cookie_value = response.cookies.get(MFL_USER_COOKIE_KEY)
        if response.status_code == 200 and cookie_value:
            logger.info("MFL login succeeded on attempt %s", attempt)
            return cookie_value
        logger.error("Login attempt %s failed (HTTP %s, cookie present: %s). Retrying...",
                     attempt, response.status_code, bool(cookie_value))
        time.sleep(SLEEP_SECONDS)

    raise RuntimeError(f"MFL login failed after {MAX_RETRIES} attempts")


def get_host() -> str:
    """Look up the league's API host for the current season.

    MFL leagues live on a numbered host (``https://wwwNN.myfantasyleague.com``)
    that can change between seasons.

    Returns:
        str: League base URL.

    Raises:
        RuntimeError: If the league export fails or has no ``baseURL``.
    """
    url = f"{MFL_API_HOST}/{YEAR}/export?TYPE=league&L={LEAGUE_ID}&JSON=1"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        base_url = response.json()["league"]["baseURL"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise RuntimeError(f"Cannot obtain MFL API host for league {LEAGUE_ID}, season {YEAR}") from exc
    if not base_url:
        raise RuntimeError("MFL league export returned an empty baseURL")
    return base_url


def pretty_print_response(response: requests.Response) -> None:
    """Log the interesting parts of an HTTP response.

    Args:
        response: Response to log. Must not be a login response (cookie).
    """
    logger.info("URL: %s", response.url)
    logger.info("Status Code: %s", response.status_code)
    logger.info("Reason: %s", response.reason)
    logger.info("Text: %s", response.text)


def build_http_get_request(base_url: str, cookie: str, query_params: dict) -> requests.Response:
    """Post to the MFL message board, retrying on non-200 responses.

    Args:
        base_url: ``{host}/{year}/import``.
        cookie: ``MFL_USER_ID`` session cookie value.
        query_params: Output of :func:`build_query_object`.

    Returns:
        requests.Response: The successful response.

    Raises:
        RuntimeError: If MFL rejects the post (200 with an ``<error>`` body,
            e.g. "Invalid League ID") or every attempt fails.
    """
    url = f"{base_url}?"
    cookies = {MFL_USER_COOKIE_KEY: cookie}

    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(url, cookies=cookies, params=query_params, timeout=REQUEST_TIMEOUT_SECONDS)
        logger.info("***MAIN REQUEST***")
        pretty_print_response(response)

        if response.status_code == 200:
            if "<error>" in response.text:
                raise RuntimeError(f"MFL rejected the post: {response.text.strip()[:200]}")
            return response
        logger.error("Attempt #%s to post to messageBoard failed with status code %s. Retrying...",
                     attempt, response.status_code)
        time.sleep(SLEEP_SECONDS)

    raise RuntimeError(f"Posting to the MFL messageBoard failed after {MAX_RETRIES} attempts")
