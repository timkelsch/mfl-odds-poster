import argparse
import boto3
import io
import json
import logging
import os
import pytz
import requests
from get_secret_value import GetSecretWrapper
from dateutil.parser import isoparse
from datetime import datetime, timedelta

PT_TIME_ZOME = pytz.timezone('US/Pacific')

logging.basicConfig(level=logging.INFO)


def fetch_game_data(source):
    if source.startswith("http"):
        response = requests.get(source)
        response.raise_for_status()  # Raise an exception for non-200 status codes
        return response.json()
    else:
        try:
            with open(source, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error reading input file: {e}")
            raise


def convert_utc_to_pacific_time(utc_time_str):
    """
    Converts a UTC time string to US Pacific time.

    Args:
        utc_time_str (str): The UTC time string in ISO 8601 format.

    Returns:
        str: The US Pacific time string in ISO 8601 format.
    """
    utc_time = datetime.fromisoformat(utc_time_str)
    pacific_time = utc_time.astimezone(pytz.timezone('US/Pacific'))
    return pacific_time.isoformat()


def adjust_times_zones(games):
    for game in games:
        game["commence_time"] = convert_utc_to_pacific_time(
            game["commence_time"])
        # game["bookmakers"][0]["last_update"] =
        # convert_utc_to_pacific_time(game["bookmakers"][0]["last_update"])
        # game["bookmakers"][0]["markets"][0]["last_update"] =
        # convert_utc_to_pacific_time(game["bookmakers"][0]["markets"][0]["last_update"])
        # game["bookmakers"][0]["markets"][1]["last_update"] =
        # convert_utc_to_pacific_time(game["bookmakers"][0]["markets"][1]["last_update"])
    return games


def get_week_start_end(date, week_start=1):
    """
    Gets the start and end dates of the current week based on a specified week start.

    Args:
        week_start (int, optional): The day of the week to consider as the
        week start (0=Monday, 1=Tuesday, ... 6=Sunday). Default is 2 (Wednesday).

    Returns:
        tuple: A tuple containing the start & end dates as datetime.date objects.
    """
    while date.weekday() != week_start:
        date -= timedelta(days=1)

    week_start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_date = (week_start_date + timedelta(days=6)
                     ).replace(hour=23, minute=59, second=59, microsecond=999)

    return week_start_date, week_end_date


def transform_game_data(games):
    start_of_week, end_of_week = get_week_start_end(
        datetime.now(tz=PT_TIME_ZOME), 1)

    # Filter games within the current week
    this_weeks_games = [
        game
        for game in games
        if isoparse(game["commence_time"]) >= start_of_week
        and
        isoparse(game["commence_time"]) <= end_of_week
    ]

    sorted_games = sorted(
        this_weeks_games, key=lambda x: isoparse(x['commence_time']))

    transformed_games = []

    for game in sorted_games:
        spreads = game["bookmakers"][0]["markets"][0]["outcomes"]
        totals = game["bookmakers"][0]["markets"][1]["outcomes"][0]["point"]

        # Find the team with the negative spread
        for outcome in spreads:
            if outcome["point"] < 0:
                negative_spread_team = outcome["name"]
                point_spread = outcome["point"]

        # Append formatted game info
        transformed_games.append({
            "commence_time": game["commence_time"],
            "favored_team": negative_spread_team,
            "away_team": game["away_team"],
            "home_team": game["home_team"],
            "point_spread": adjust_float(point_spread),
            "totals_point": adjust_float(totals)
        })

    return transformed_games


def format_games(formatted_games):
    current_day = None

    buffer = io.StringIO()

    for game in formatted_games:
        game_day = isoparse(game["commence_time"]).strftime("%A")  # Get day of the week
        if game_day != current_day:  # Print day heading if day changes
            current_day = game_day
            buffer.write(f"\n*** {current_day.upper()} ***\n\n")

        if game['favored_team'] == game['away_team']:
            buffer.write(
                f"{game['away_team']} | {game['point_spread']} | {game['totals_point']}\n")
            buffer.write(f"{game['home_team']}\n\n")
        else:
            buffer.write(f"{game['away_team']}\n")
            buffer.write(
                f"{game['home_team']} | {game['point_spread']} | {game['totals_point']}\n\n")

    return buffer.getvalue()


def adjust_float(num):
    if num.is_integer():
        if num > 0:
            return num + 0.5
        else:
            return num - 0.5
    else:
        return num


def get_secret(secret_name):
    """
    Retrieve a secret from AWS Secrets Manager.

    :param secret_name: Name of the secret to retrieve.
    :type secret_name: str
    """
    try:
        # Validate secret_name
        if not secret_name:
            raise ValueError("Secret name must be provided.")
        # Retrieve the secret by name
        client = boto3.client("secretsmanager")
        wrapper = GetSecretWrapper(client)
        secret = wrapper.get_secret(secret_name)
        # Note: Secrets should not be logged.
        return secret
    except Exception as e:
        logging.error(f"Error retrieving secret: {e}")
        raise


def main():
    # https://the-odds-api.com/liveapi/guides/v4/#overview
    API_BASE_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
    API_PARAMETERS = "?regions=us&markets=spreads,totals&bookmakers=draftkings&apiKey="
    ENV_VAR_SECRET_ARN = "SECRET_ARN"

    parser = argparse.ArgumentParser(description="Process football game data")
    parser.add_argument("source", nargs="?", type=str,
                        help="File path or URL for the JSON data (optional)")
    args = parser.parse_args()

    secret_arn = os.environ.get(ENV_VAR_SECRET_ARN)
    if secret_arn is None:
        raise KeyError(
            logging.error(f"Environment variable is not set: {ENV_VAR_SECRET_ARN}"))

    if args.source:
        logging.info(f"Using local file: {args.source}")
        games_data = fetch_game_data(args.source)
    else:
        url = API_BASE_URL + API_PARAMETERS + get_secret(secret_arn)
        logging.info(f"Using API URL: {API_BASE_URL + API_PARAMETERS}")
        games_data = fetch_game_data(url)

    adjust_times_zones(games_data)
    transformed_game_data = transform_game_data(games_data)
    jimbo = str(format_games(transformed_game_data))
    response = {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/plain"
        },
        "body": jimbo
    }

    return response


if __name__ == "__main__":
    output = main()["body"]
    print(output)


def lambda_handler(event, context):
    output = main()
    return output

