import argparse
import io
import json
import os
import pytz
import requests
from dateutil.parser import isoparse
from datetime import datetime, timedelta

DATE_FORMAT_INPUT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT_SECONDARY = "%Y-%m-%dT%H:%M:%S"
PT_TIME_ZOME = pytz.timezone('US/Pacific')

def fetch_game_data(source):
  if source.startswith("http"):
    response = requests.get(source)
    response.raise_for_status()  # Raise an exception for non-200 status codes
    return response.json()
  else:
    with open(source, "r") as f:
      return json.load(f)

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
    game["commence_time"] = convert_utc_to_pacific_time(game["commence_time"])
    game["bookmakers"][0]["last_update"] = convert_utc_to_pacific_time(game["bookmakers"][0]["last_update"])
    game["bookmakers"][0]["markets"][0]["last_update"] = convert_utc_to_pacific_time(game["bookmakers"][0]["markets"][0]["last_update"])
    game["bookmakers"][0]["markets"][1]["last_update"] = convert_utc_to_pacific_time(game["bookmakers"][0]["markets"][1]["last_update"])
  return games

def get_week_start_end(date, week_start=2):
    """
    Gets the start and end dates of the current week based on a specified week start.

    Args:
        week_start (int, optional): The day of the week to consider as the week start (0=Monday, 1=Tuesday, ... 6=Sunday).
            Default is 2 (Wednesday).

    Returns:
        tuple: A tuple containing the start and end dates as datetime.date objects.
    """
    while date.weekday() != week_start:
        date -= timedelta(days=1)

    week_start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_date = (week_start_date + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    return week_start_date, week_end_date

def transform_game_data(games):
  start_of_week, end_of_week = get_week_start_end(datetime.now(tz=PT_TIME_ZOME), 2)

  # Filter games within the current week
  this_weeks_games = [
      game
      for game in games
      if isoparse(game["commence_time"]) >= start_of_week and isoparse(game["commence_time"]) <= end_of_week
  ]
  
  sorted_games = sorted(this_weeks_games, key=lambda x: isoparse(x['commence_time']))

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
      buffer.write(f"{game['away_team']} | {game['point_spread']} | {game['totals_point']}\n")
      buffer.write(f"{game['home_team']}\n\n")
    else:
      buffer.write(f"{game['away_team']}\n")
      buffer.write(f"{game['home_team']} | {game['point_spread']} | {game['totals_point']}\n\n")
  
  return buffer.getvalue()

def adjust_float(num):
  if num.is_integer():
    if num > 0:
      return num + 0.5
    else:
      return num - 0.5
  else:
    return num


def main():
  # https://the-odds-api.com/liveapi/guides/v4/#overview
  API_BASE_URL="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
  API_PARAMETERS="?regions=us&markets=spreads,totals&bookmakers=draftkings&apiKey="
  ENV_VAR_API_KEY_THE_ODDS="API_KEY_THE_ODDS"
    
  parser = argparse.ArgumentParser(description="Process football game data")
  parser.add_argument("source", nargs="?", type=str, help="File path or URL for the JSON data (optional)")
  args = parser.parse_args()

  apiKey = os.environ.get(ENV_VAR_API_KEY_THE_ODDS)
  if apiKey is None:
    raise KeyError(f"{ENV_VAR_API_KEY_THE_ODDS} environment variable is not set.")
    
  if args.source:
    games_data = fetch_game_data(args.source)
  else:
    games_data = fetch_game_data(API_BASE_URL + API_PARAMETERS + apiKey)

  adjust_times_zones(games_data)
  transformed_game_data = transform_game_data(games_data)
  return format_games(transformed_game_data)

if __name__ == "__main__":
  print(main())

def lambda_handler(event, context):
  main()

## TITLE: Week $WEEK: Three Leg Parlay
## ASDF