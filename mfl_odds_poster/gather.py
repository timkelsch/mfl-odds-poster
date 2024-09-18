import argparse
import json
import os
import pprint
import pytz
import requests
from datetime import datetime, timedelta

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

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

def transform_game_data(games):
  start_of_week, end_of_week = get_current_week_range()
  
#   print("commence_time: ", datetime.strptime(games[0]["commence_time"], DATE_FORMAT))
#   print("start_time: ", datetime.strptime(start_of_week, "%Y-%m-%d"))
#   print("end_time: ", datetime.strptime(end_of_week, "%Y-%m-%d"))

  # Filter games within the current week
  filtered_games = [
      game
      for game in games
      if datetime.strptime(game["commence_time"], DATE_FORMAT) >= datetime.strptime(start_of_week, "%Y-%m-%d") and
      datetime.strptime(game["commence_time"], DATE_FORMAT) <= datetime.strptime(end_of_week, "%Y-%m-%d")
  ]
  
  games_sorted = sorted(filtered_games, key=lambda x: datetime.strptime(x['commence_time'], DATE_FORMAT))
    
  formatted_games = []
  
  current_day = None
  
  for game in games_sorted:
    # pprint.pprint(game)
    game_day = datetime.strptime(game["commence_time"], DATE_FORMAT).strftime("%A")  # Get day of the week
    print(f"game_day: {game_day}")
    print(f"current_day: {current_day}")
    if game_day != current_day:  # Print day heading if day changes
      current_day = game_day
      print(f"\n** {current_day.upper()} **")

    spreads = game["bookmakers"][0]["markets"][0]["outcomes"]
    totals = game["bookmakers"][0]["markets"][1]["outcomes"][0]["point"]

    # Find the team with the negative spread
    for outcome in spreads:
      if outcome["point"] < 0:
        negative_spread_team = outcome["name"]
        point_spread = outcome["point"]

    # Append formatted game info
    formatted_games.append({
      "favored_team": negative_spread_team,
      "away_team": game["away_team"],
      "home_team": game["home_team"],
      "point_spread": adjust_float(point_spread),
      "totals_point": adjust_float(totals)
    })

  # Output the result in the desired format
  for game in formatted_games:
    if game['favored_team'] == game['away_team']:
      print(f"{game['away_team']} | {game['point_spread']} | {game['totals_point']}")
      print(f"{game['home_team']}\n")
    else:
      print(f"{game['away_team']}")
      print(f"{game['home_team']} | {game['point_spread']} | {game['totals_point']}\n")

def adjust_float(num):
  if num.is_integer():
    if num > 0:
      return num + 0.5
    else:
      return num - 0.5
  else:
    return num

def get_current_week_range():
  """
  This function defines the current week as Wednesday to Tuesday.
  """
  return "2024-09-18", "2024-09-24"
#   today = datetime.today()
#   todays_day = today.weekday()
#   print("todays_day: ", todays_day)
#   # Get the wednesday of the current week
#   start_of_week = today - timedelta(days = 7 - todays_day)
#   # Get the tuesday of the next week (current week + 6 days)
#   end_of_week = start_of_week + timedelta(days = 6)
#   print("start_of_week: ", start_of_week)
#   print("end_of_week: ", end_of_week)
#   return start_of_week.strftime("%Y-%m-%d"), end_of_week.strftime("%Y-%m-%d")

def main():
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
  transform_game_data(games_data)

if __name__ == "__main__":
  main()


## TITLE: Week $WEEK: Three Leg Parlay