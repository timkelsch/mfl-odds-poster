import boto3
import datetime
import json
import logging
import os
import pprint
import requests
import time
import urllib.parse

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_RETRIES = 3
SLEEP_SECONDS = 3


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
        return value
    except KeyError:
        logging.error(f"Environment variable {var_name} is not set.")
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

    raise Exception("Maximum number of login attempts reached.")


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
        logger.error(f"ERROR: Cannot obtain API host\n{e}")


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

    raise Exception("ERROR: Maximum number of attempts to post to messageBoard reached.")


SUBSECRET_KEY = "the-odds-api-key"
# checkov:skip=CKV_SECRET_6: not a secret
MFL_LOGIN_URL = "https://api.myfantasyleague.com/2024/login?"
ENV_VAR_SECRET_ARN = "SECRET_ARN"
MFL_USER_COOKIE_KEY = "MFL_USER_ID"
REQUEST_TYPE = "messageBoard"
YEAR = datetime.date.today().year
API = "import"
LEAGUE_ID = "15781"
FRANCHISE_ID = "0008"
SUBJECT = ""
THREAD = "6480193"
# BODY = "marc<br>hermsmeyer<br>did<br>what?!|"


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

def lambda_handler(event, context):
    cookie = login()
    logger.info(f"cookie: {cookie}")
    host = get_host()
    # logger.info(f"event: {event['Payload']}")
    body = json.loads(event['body'])
    query_object = build_query_object(REQUEST_TYPE, LEAGUE_ID, FRANCHISE_ID, THREAD, SUBJECT, body)
    response = build_http_get_request(f"{host}/{YEAR}/{API}", cookie, query_object)
    pretty_print_response(response)
