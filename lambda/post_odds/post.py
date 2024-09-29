import boto3
import datetime
import json
import logging
import os
import pprint
import requests
import sys
import time
import urllib.parse

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_RETRIES = 3
SLEEP_SECONDS = 3
MFL_LOGIN_URL = "https://api.myfantasyleague.com/2024/login?"
ENV_VAR_SECRET_ARN = "SECRET_ARN"
SUBSECRET_KEY_THEODDS_API_KEY = "the-odds-api-key"
# checkov:skip=CKV_SECRET_6: not a secret
NFL_API_URL = "https://nfl-football-api.p.rapidapi.com/nfl-whitelist"
SUBSECRET_KEY_NFL_API_API_KEY = "nfl-api-key"

MFL_USER_COOKIE_KEY = "MFL_USER_ID"
REQUEST_TYPE = "messageBoard"
YEAR = datetime.date.today().year
API = "import"
LEAGUE_ID = "15781"
FRANCHISE_ID = "0008"
# SUBJECT = ""
THREAD = ""  # "6480193" == test thread


def lambda_handler(event, context):
    cookie = login()
    logger.info(f"cookie: {cookie}")
    host = get_host()
    try:
        body = event['body']['body']
    except KeyError as e:
        logging.error(f"ERROR: Cannot retrieve data from calling lambda event:\n{e}")

    first_day_regular_season = get_current_nfl_season_first_day()
    week_1_start_date, week_1_end_date = get_week_start_end(first_day_regular_season)
    week = get_current_nfl_week(week_1_start_date, datetime.datetime.now(datetime.timezone.utc))
    subject = f"Week {week}: Three-Leg Parlay"
    logger.info(f"subject: {subject}")

    query_object = build_query_object(REQUEST_TYPE, LEAGUE_ID, FRANCHISE_ID, THREAD, subject, body)
    response = build_http_get_request(f"{host}/{YEAR}/{API}", cookie, query_object)
    pretty_print_response(response)


def get_current_nfl_week(first_game_date, input_date):
  """
  Calculates the NFL week number based on the input date and the first game date.

  Args:
    input_date: The input date as a datetime.date object.
    first_game_date: The date of the first regular season game as a datetime.date object.

  Returns:
    The NFL week number.
  """

  # Calculate the difference in days between the input date and the first game date
  days_since_first_game = (input_date - first_game_date).days
  logger.info(f"days_since_first_game: {days_since_first_game}")
  # Calculate the NFL week number (assuming Tuesday starts the week)
  nfl_week = days_since_first_game // 7 + 1

  return nfl_week


def get_current_nfl_season_first_day():
    secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
    api_key = get_secret(secret_arn, SUBSECRET_KEY_NFL_API_API_KEY)
    headers = {
        "rapidapi-host": "nfl-football-api.p.rapidapi.com",
        "rapidapi-key": api_key
    }
    response = requests.get(NFL_API_URL, headers=headers)
    response.raise_for_status()

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        data = response.text  # If the response is not JSON, return the text as is
        
    startDate = ""
    try:
        # Iterate through the "sections" list
        for section in data["sections"]:
            # Check if the section is "Regular Season"
            if section["label"] == "Regular Season":
                # Iterate through the "entries" list within the section
                for entry in section["entries"]:
                    # Check if the entry is Week 1
                    if entry["label"] == "Week 1":
                        # Return the start date
                        startDate = entry["startDate"]
    except KeyError as e:
        logger.error(f"Error parsing NFL API response: {e}")
        sys.exit(1)

    datetime_startDate = datetime.datetime.fromisoformat(startDate)

    logger.info(f"datetime_startDate: {datetime_startDate}")
    return datetime_startDate


def get_week_start_end(date, week_start=1):
    """
    This is going to be in UTC meaning that start will be 5pm PT (UTC midnight)
    monday night which is okay because this will run on Wednesday evening via cron
    and we're only using this to determine what NFL week we're currently in.
    """
    while date.weekday() != week_start:
        date -= datetime.timedelta(days=1)

    week_start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_date = (week_start_date + datetime.timedelta(days=6)
                     ).replace(hour=23, minute=59, second=59, microsecond=999)

    return week_start_date, week_end_date


def build_query_object(request_type, league_id, franchise_id, thread, subject, body):
    query_params = {
        "TYPE": request_type,
        "L": league_id,
        "FRANCHISE_ID": franchise_id,
        "THREAD": thread,
        "SUBJECT": subject,
        "BODY": body,
        "JSON": 1
    }
    return query_params


def get_secret(secret_name, subsecret_key):
    """
    Retrieve a secret from AWS Secrets Manager.

    :param secret_name: Name of the secret to retrieve.
    :type secret_name: str
    """
    try:
        if not secret_name:
            raise ValueError("Secret name must be provided.")

        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        secret_string = response['SecretString']

        # Note: Secrets should not be logged.
        secret_data = json.loads(secret_string)
        secret_value = secret_data[subsecret_key]
        return secret_value
    except Exception as e:
        logging.error(f"Error retrieving secret: {e}")
        raise


def get_env_var(var_name):
    """
    Retrieve an environment variable.

    :param var_name: Name of the environment variable.
    :type var_name: str
    """
    try:
        value = os.environ.get(var_name)
        logger.info("Accessed environment variable")
        return value
    except KeyError:
        logging.error(f"A required environment variable is not set.")
        raise


def login():
    secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
    username = get_secret(secret_arn, 'mfl-username')
    password = get_secret(secret_arn, 'mfl-password')
    
    url = MFL_LOGIN_URL
    data = {"USERNAME": username, "PASSWORD": password, "XML": 1}

    # Send POST request with HTTPS
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(url, headers=headers, data=data, verify=True)
        pretty_print_response(response)

        if response.status_code == 200:
            cookie_data = response.cookies.get_dict()
            cookie_value = cookie_data[MFL_USER_COOKIE_KEY]
            # print(f"cookie_value: {cookie_value}")
            return cookie_value
        else:
            logging.error(f"Login attempt {attempt} failed with status code {response.status_code}. Retrying...")
            time.sleep(SLEEP_SECONDS)

    logger.error("ERROR: Maximum number of login attempts reached.")
    sys.exit(1)


def get_host():
    url = "https://api.myfantasyleague.com/2024/export?TYPE=league&L=15781&JSON=1"
    
    try:
        response = requests.get(url)
        # TODO: Go back and integrate this baseURL with the rest of the project

        data = response.json()  # Parse the JSON response
        base_url = data["league"]["baseURL"]
        if base_url:
            return base_url
    except Exception as e:
        logger.error(f"ERROR: Cannot obtain API host. {e}")


def pretty_print_response(response):
    """
    Pretty-prints a HTTP response object.

    Args:
        response: The HTTP response object.
    """

    logger.info(f"URL: {response.url}")
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Reason: {response.reason}")
    logger.info(f"Request: {response.request}")
    logger.info(f"Text: {response.text}")
    logger.info(f"Content: {response.content}")
    # logger.info(f"Headers:")
    # pprint.pprint(dict(response.headers))


def build_http_get_request(base_url, cookie, query_params):
    url = f"{base_url}?"
    logging.info(f"url: {url}")
    cookies = { f"{MFL_USER_COOKIE_KEY}": f"{cookie}" }

    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(url, cookies=cookies, params=query_params, verify=True)
        logger.info("***MAIN REQUEST***")
        pretty_print_response(response)

        if response.status_code == 200:
            return response
        else:
            logging.error(f"Attempt #{attempt} to post to messageBoard failed with status code {response.status_code}. Retrying...")
            time.sleep(SLEEP_SECONDS)

    logger.error("ERROR: Maximum number of attempts to post to messageBoard reached. Exiting.")
    sys.exit(1)

