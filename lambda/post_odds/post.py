import boto3
import json
import logging
import os
import pprint
import requests

MFL_LOGIN_URL = "https://api.myfantasyleague.com/2024/login?"
SUBSECRET_KEY = "the-odds-api-key"
# checkov:skip=CKV_SECRET_6: not a secret
ENV_VAR_SECRET_ARN = "SECRET_ARN"
MFL_USER_COOKIE_KEY = "MFL_USER_ID"
# TODO: look this up instead of hard coding

logging.basicConfig(level=logging.INFO)


def get_secret(secret_name, subsecret_key):
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
    # Retrieve username and password from AWS Secrets Manager
    secret_arn = get_env_var(ENV_VAR_SECRET_ARN)
    username = get_secret(secret_arn, 'mfl-username')
    password = get_secret(secret_arn, 'mfl-password')
    
    # Prepare login request
    url = MFL_LOGIN_URL
    data = {"USERNAME": username, "PASSWORD": password, "XML": 1}

    # Send POST request with HTTPS
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response = requests.post(url, headers=headers, data=data, verify=True)
    print(f"response: {response}")
    print(f"body: {response.headers}")
    # try:
    #   response_json = response.json()
    #   print(json.dumps(response_json, indent=2))
    # except json.decoder.JSONDecodeError:
    print(f"response.text: {response.text}")
    
    # Check response status
    if response.status_code == 200:
        # Extract cookie information
        cookie_data = response.cookies.get_dict()
        print(f"cookie_data: {cookie_data}")

        cookie_value = cookie_data[MFL_USER_COOKIE_KEY]
        print(f"cookie_value: {cookie_value}")
        return cookie_value

        # Return success message and cookie
        # return {
        #     'statusCode': 200,
        #     'body': json.dumps({
        #         'message': 'Login successful!',
        #         'cookie': f"Cookie: {cookie_name}={cookie_value}"
        #     })
        # }
    else:
        return "ERROR"
        # Return error message
        # return {
        #     'statusCode': response.status_code,
        #     'body': json.dumps({
        #         'message': f"Login failed with status code: {response.status_code}"
        #     })
        # }


def get_host():
    url = "https://api.myfantasyleague.com/2024/export?TYPE=league&L=15781&JSON=1"
    response = requests.get(url)
    # TODO: Go back and integrate this baseURL with the rest of the project

    if response.status_code == 200:
        data = response.json()  # Parse the JSON response
        base_url = data["league"]["baseURL"]  # Access the base URL using .get() for optional value
        if base_url:
            print(f"Base URL from JSON: {base_url}")
            return base_url
        else:
            print("Base URL not found in the JSON response.")
    else:
        print(f"Error retrieving data: {response.status_code}")


def check_import_message_thread(caookie_crisp):
    # cookie_name = "MFL_USER_ID"
    # cookie_value = "your_cookie_value"
    API = "import?"
    YEAR = 2024  # TODO: Be better
    LEAGUE_ID = "15781"  # TODO: put all of this somewhere less dumb
    FRANCHISE_ID = "0008"
    THREAD = "6479288"
    BODY = "remember that chick in high school? yeah, marc spermsmeyer ate her lunch."
    
    host = get_host()
    headers = {
        f"{MFL_USER_COOKIE_KEY}": f"{caookie_crisp}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    print(f"headers: {headers}")
    data = {
        "TYPE": "messageBoard",
        "L": LEAGUE_ID,
        "FRANCHISE_ID": FRANCHISE_ID,
        "THREAD": THREAD,
        "BODY": BODY,
        "JSON": 1
    }

    url = f"{host}/{YEAR}/{API}"
    print(f"url: {url}")

    # Send POST request with HTTPS
    response = requests.post(url, headers=headers, data=data, verify=True)
    print(f"content: {response.content}")
    pretty_print_response(response.json())
    return response


def pretty_print_response(response):
    """
    Pretty-prints a HTTP response object.

    Args:
        response: The HTTP response object.
    """

    print(f"Status Code: {response.status_code}")
    print(f"Headers:")
    pprint.pprint(dict(response.headers))

    try:
        response_json = response.json()
        print(json.dumps(response_json, indent=2))
    except json.decoder.JSONDecodeError:
        print(f"Response body: {response.text}")


def lambda_handler(event, context):
    cookie = login()
    print(f"cookie: {cookie}")
    host = get_host()
    print(f"host: {host}")
    response = check_import_message_thread(cookie)
    pretty_print_response(response)
