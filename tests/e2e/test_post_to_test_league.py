"""End-to-end: deployed test stack posts the weekly odds to MFL copy league 22744.

Run with ``pytest -m e2e`` after ``cdk deploy MflOddsPosterStackTest``. Needs AWS
credentials that can read the test stack, invoke its lambdas and read
``/mfl-odds`` (the CI OIDC role, or ``AWS_PROFILE=pmfl`` locally).

Safety: this only ever targets ``MflOddsPosterStackTest`` and aborts before
invoking anything unless the deployed poster is configured for league 22744.
"""
import datetime as dt
import json
import os
import time

import boto3
import pytest

import post
from tests.e2e import mfl_board

pytestmark = pytest.mark.e2e

STACK_NAME = "MflOddsPosterStackTest"
TEST_LEAGUE_ID = "22744"
FRANCHISE_ID = "0008"
CONFIG_PARAMETER = "/mfl-odds"
REGION = os.environ.get("AWS_REGION", "us-east-1")
POLL_SECONDS = 60
CLOCK_SKEW_SECONDS = 30


@pytest.fixture(scope="module")
def outputs() -> dict:
    """Test stack outputs (function names)."""
    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK_NAME)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def test_weekly_post_lands_on_test_league_board(outputs: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gather -> poster -> MFL: the post on 22744 matches what gather produced."""
    lambda_client = boto3.client("lambda", region_name=REGION)

    # Guard: never invoke anything that could post outside the copy league.
    poster_env = lambda_client.get_function_configuration(
        FunctionName=outputs["PosterFunctionName"])["Environment"]["Variables"]
    assert poster_env.get("LEAGUE_ID") == TEST_LEAGUE_ID, \
        f"Refusing to run: poster targets league {poster_env.get('LEAGUE_ID')}"
    assert poster_env.get("CONFIG_PARAMETER_NAME") == CONFIG_PARAMETER

    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=CLOCK_SKEW_SECONDS)
    response = lambda_client.invoke(FunctionName=outputs["GatherFunctionName"], InvocationType="RequestResponse")
    payload = response["Payload"].read().decode("utf-8")
    assert "FunctionError" not in response, f"Gather/poster failed: {payload[:1000]}"
    sent_body = json.loads(payload)["body"]
    if mfl_board.in_season(started.date()):
        assert mfl_board.normalize_body(sent_body), "In season but gather produced an empty odds body"

    # Read the board as the copy account (same login code path as the poster).
    monkeypatch.setenv("CONFIG_PARAMETER_NAME", CONFIG_PARAMETER)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    cookie = post.login()
    host = post.get_host(TEST_LEAGUE_ID)
    subject = mfl_board.expected_subject(dt.datetime.now(dt.timezone.utc))

    thread = None
    deadline = time.monotonic() + POLL_SECONDS
    while thread is None and time.monotonic() < deadline:
        board = mfl_board.export(host, cookie, {"TYPE": "messageBoard", "L": TEST_LEAGUE_ID})
        threads = mfl_board.as_list((board.get("messageBoard") or {}).get("thread"))
        thread = mfl_board.find_new_thread(threads, subject, started)
        if thread is None:
            time.sleep(5)
    assert thread is not None, f"No new thread '{subject}' on league {TEST_LEAGUE_ID} within {POLL_SECONDS}s"

    opening = mfl_board.first_post(mfl_board.export(
        host, cookie, {"TYPE": "messageBoardThread", "L": TEST_LEAGUE_ID, "THREAD": thread["id"]}))
    assert opening["franchise"] == FRANCHISE_ID
    assert mfl_board.normalize_body(opening["body"]) == mfl_board.normalize_body(sent_body)
