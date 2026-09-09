"""Unit tests for the MflOddsPosterStack CDK stack."""
import aws_cdk as core
import aws_cdk.assertions as assertions
import pytest

from mfl_odds_poster.mfl_odds_poster_stack import MflOddsPosterStack


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesize the stack once with asset bundling disabled.

    Returns:
        assertions.Template: Synthesized CloudFormation template.
    """
    app = core.App(context={"aws:cdk:bundling-stacks": []})
    stack = MflOddsPosterStack(app, "mfl-odds-poster")
    return assertions.Template.from_stack(stack)


def test_schedule_fires_wednesday_afternoon(template: assertions.Template) -> None:
    """Rule must fire Wednesday 22:00 UTC, before any Wed/Thu kickoff.

    Args:
        template: Synthesized stack template.
    """
    template.has_resource_properties(
        "AWS::Events::Rule",
        {"ScheduleExpression": "cron(0 22 ? * 4 *)", "State": "ENABLED"},
    )


def test_gather_timeout_exceeds_poster_timeout(template: assertions.Template) -> None:
    """Gather waits on the poster synchronously, so its timeout must be larger.

    Args:
        template: Synthesized stack template.
    """
    functions = template.find_resources("AWS::Lambda::Function")
    timeouts = {
        props["Properties"]["Handler"]: props["Properties"]["Timeout"]
        for props in functions.values()
        if "Handler" in props["Properties"] and props["Properties"]["Handler"].endswith("lambda_handler")
    }
    assert timeouts == {"post.lambda_handler": 30, "gather.lambda_handler": 60}
