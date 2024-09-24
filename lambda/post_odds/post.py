import boto3
import json
import logging
import os
import requests

MFL_LOGIN_URL = "https://api.myfantasyleague.com/2024/login?XML=1"
SUBSECRET_KEY = "the-odds-api-key"
# checkov:skip=CKV_SECRET_6: not a secret
ENV_VAR_SECRET_ARN = "SECRET_ARN"
REGION = "us-east-1"
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
        secret_data = json.loads(secret)
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
    username = get_secret(secret_arn, 'mfl_username')
    password = get_secret(secret_arn, 'mfl-password')
    
    # Prepare login request
    url = MFL_LOGIN_URL
    data = {"USERNAME": username, "PASSWORD": password}

    # Send POST request with HTTPS
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response = requests.post(url, headers=headers, data=data, verify=True)

    # Check response status
    if response.status_code == 200:
        # Extract cookie information
        cookie_data = response.cookies.get_dict()
        cookie_name = list(cookie_data.keys())[0]
        cookie_value = cookie_data[cookie_name]

        # Return success message and cookie
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Login successful!',
                'cookie': f"Cookie: {cookie_name}={cookie_value}"
            })
        }
    else:
        # Return error message
        return {
            'statusCode': response.status_code,
            'body': json.dumps({
                'message': f"Login failed with status code: {response.status_code}"
            })
        }

def lambda_handler(event, context):
    login()
