"""Fetch this week's NFL odds from the-odds-api and hand them to the poster lambda."""
import argparse
import io
import json
import logging
import os
from datetime import datetime, timedelta

import boto3
import pytz
import requests
from dateutil.parser import isoparse
from get_secret_value import GetSecretWrapper

PT_TIME_ZOME = pytz.timezone('US/Pacific')
POSTER_LAMBDA_ARN = "POSTER_LAMBDA_ARN"
REQUEST_TIMEOUT_SECONDS = 10

# https://the-odds-api.com/liveapi/guides/v4/#overview
API_BASE_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
API_PARAMETERS = "?regions=us&markets=spreads,totals&bookmakers=draftkings&apiKey="
ENV_VAR_SECRET_ARN = "SECRET_ARN"
SUBSECRET_KEY = "the-odds-api-key"
# checkov:skip=CKV_SECRET_6: not a secret

logging.basicConfig(level=logging.INFO)


def fetch_game_data(source: str) -> list:
    """Load odds JSON from a URL or a local file.

    Args:
        source: ``http(s)://`` URL or a filesystem path.

    Returns:
        list: Parsed the-odds-api game list.

    Raises:
        requests.RequestException: On network errors or non-2xx responses.
        OSError: If the local file cannot be read.
        json.JSONDecodeError: If the local file is not valid JSON.
    """
    if source.startswith("http"):
        response = requests.get(source, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    with open(source, "r", encoding="utf-8") as handle:
        return json.load(handle)


def convert_utc_to_pacific_time(utc_time_str: str) -> str:
    """Convert an ISO 8601 UTC timestamp to US Pacific time.

    Args:
        utc_time_str: UTC time string in ISO 8601 format (``Z`` suffix accepted).

    Returns:
        str: Pacific time string in ISO 8601 format.
    """
    utc_time = datetime.fromisoformat(utc_time_str)
    pacific_time = utc_time.astimezone(PT_TIME_ZOME)
    return pacific_time.isoformat()


def adjust_times_zones(games: list) -> list:
    """Rewrite each game's ``commence_time`` from UTC to Pacific, in place.

    Args:
        games: the-odds-api game list.

    Returns:
        list: The same list, mutated.
    """
    for game in games:
        game["commence_time"] = convert_utc_to_pacific_time(game["commence_time"])
    return games


def get_week_start_end(date: datetime, week_start: int = 1) -> tuple[datetime, datetime]:
    """Return the bounds of the NFL week containing ``date``.

    Args:
        date: Any datetime inside the week.
        week_start: ``datetime.weekday()`` value that begins a week
            (0=Monday, 1=Tuesday ... 6=Sunday).

    Returns:
        tuple[datetime, datetime]: Week start (00:00) and end (23:59:59).
    """
    while date.weekday() != week_start:
        date -= timedelta(days=1)

    week_start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_date = (week_start_date + timedelta(days=6)
                     ).replace(hour=23, minute=59, second=59, microsecond=999)

    return week_start_date, week_end_date


def transform_game_data(games: list, now: datetime | None = None) -> list:
    """Reduce this week's games to favored team, spread and total.

    Games outside the current Tuesday-to-Monday week, or without both a
    ``spreads`` and a ``totals`` market from the first bookmaker, are dropped.
    A pick'em (no negative spread) is attributed to the home team at 0, which
    :func:`adjust_float` renders as -0.5.

    Args:
        games: the-odds-api game list with Pacific ``commence_time`` values.
        now: Reference time for "this week". Defaults to now in Pacific time.

    Returns:
        list: Sorted list of dicts with ``commence_time``, ``favored_team``,
        ``away_team``, ``home_team``, ``point_spread`` and ``totals_point``.
    """
    now = now or datetime.now(tz=PT_TIME_ZOME)
    start_of_week, end_of_week = get_week_start_end(now, 1)

    this_weeks_games = [
        game
        for game in games
        if start_of_week <= isoparse(game["commence_time"]) <= end_of_week
    ]

    sorted_games = sorted(this_weeks_games, key=lambda x: isoparse(x['commence_time']))

    transformed_games = []

    for game in sorted_games:
        bookmakers = game.get("bookmakers") or []
        markets = {market["key"]: market for market in bookmakers[0]["markets"]} if bookmakers else {}
        if "spreads" not in markets or "totals" not in markets:
            logging.warning("Skipping %s @ %s: bookmaker has no spreads/totals yet",
                            game["away_team"], game["home_team"])
            continue

        spreads = markets["spreads"]["outcomes"]
        totals = markets["totals"]["outcomes"][0]["point"]

        favored = next((outcome for outcome in spreads if outcome["point"] < 0), None)
        if favored is None:
            favored_team, point_spread = game["home_team"], 0.0
        else:
            favored_team, point_spread = favored["name"], favored["point"]

        transformed_games.append({
            "commence_time": game["commence_time"],
            "favored_team": favored_team,
            "away_team": game["away_team"],
            "home_team": game["home_team"],
            "point_spread": adjust_float(point_spread),
            "totals_point": adjust_float(totals)
        })

    return transformed_games


def format_games(formatted_games: list, newline_symbol: str) -> str:
    """Render games grouped by weekday, favored team carrying the line.

    Args:
        formatted_games: Output of :func:`transform_game_data`.
        newline_symbol: ``"\\n"`` for the CLI, ``"<br>"`` for the MFL board.

    Returns:
        str: Formatted text.
    """
    current_day = None

    buffer = io.StringIO()

    for game in formatted_games:
        game_day = isoparse(game["commence_time"]).strftime("%A")
        if game_day != current_day:
            current_day = game_day
            buffer.write(f"{newline_symbol}*** {current_day.upper()} ***{newline_symbol}{newline_symbol}")

        if game['favored_team'] == game['away_team']:
            buffer.write(
                f"{game['away_team']} | {game['point_spread']} | {game['totals_point']}{newline_symbol}")
            buffer.write(f"{game['home_team']}{newline_symbol}{newline_symbol}")
        else:
            buffer.write(f"{game['away_team']}{newline_symbol}")
            buffer.write(
                f"{game['home_team']} | {game['point_spread']} | {game['totals_point']}{newline_symbol}{newline_symbol}")

    return buffer.getvalue()


def adjust_float(num: float) -> float:
    """Push whole-number lines off the integer so the parlay cannot push.

    Args:
        num: Spread or total. Ints are accepted (JSON may omit ``.0``).

    Returns:
        float: ``num`` moved half a point away from zero if it was whole.
    """
    num = float(num)
    if num.is_integer():
        return num + 0.5 if num > 0 else num - 0.5
    return num


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
        json.JSONDecodeError: If the secret string is not JSON.
        KeyError: If ``subsecret_key`` is not in the secret.
    """
    if not secret_name:
        raise ValueError("Secret name must be provided.")
    client = boto3.client("secretsmanager")
    wrapper = GetSecretWrapper(client)
    secret_data = json.loads(wrapper.get_secret(secret_name))
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


def main(newline_symbol: str, source: str | None = None) -> dict:
    """Fetch, filter and format this week's odds.

    Args:
        newline_symbol: Line separator for the rendered text.
        source: Optional local file or URL; when omitted, the-odds-api is
            queried with the key from Secrets Manager.

    Returns:
        dict: API-Gateway-style response with the text in ``body``.
    """
    if source:
        logging.info("Using local source: %s", source)
        games_data = fetch_game_data(source)
    else:
        secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
        url = API_BASE_URL + API_PARAMETERS + get_secret(secret_arn, SUBSECRET_KEY)
        logging.info("Using API URL: %s", API_BASE_URL + API_PARAMETERS)
        games_data = fetch_game_data(url)

    adjust_times_zones(games_data)
    transformed_game_data = transform_game_data(games_data)
    text = format_games(transformed_game_data, newline_symbol)
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/plain"
        },
        "body": text
    }


def lambda_handler(_event: dict, _context: object) -> dict:
    """Gather this week's odds and invoke the poster lambda synchronously.

    Args:
        _event: EventBridge or API Gateway event (unused).
        _context: Lambda context (unused).

    Returns:
        dict: The response handed to the poster lambda.

    Raises:
        RuntimeError: If the poster lambda reports a function error.
    """
    body = main("<br>")
    poster_lambda_arn = get_env_var(POSTER_LAMBDA_ARN)

    response = boto3.client('lambda').invoke(
        FunctionName=poster_lambda_arn,
        Payload=json.dumps({"body": body})
    )
    payload = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        raise RuntimeError(f"Poster lambda failed ({response['FunctionError']}): {payload[:500]}")
    logging.info("Poster lambda response: %s", payload[:500])

    return body


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process football game data")
    parser.add_argument("source", nargs="?", type=str,
                        help="File path or URL for the JSON data (optional)")
    print(main("\n", parser.parse_args().source)["body"])
