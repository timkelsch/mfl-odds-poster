"""Unit tests for the MflOddsPosterStack CDK stack (prod and test variants)."""
import aws_cdk as core
import aws_cdk.assertions as assertions
import pytest

from mfl_odds_poster.mfl_odds_poster_stack import MflOddsPosterStack, PROD_LEAGUE_ID

POSTER = "post.lambda_handler"
GATHER = "gather.lambda_handler"


def _synth(construct_id: str, **kwargs) -> assertions.Template:
    """Synthesize one stack with asset bundling disabled.

    Args:
        construct_id: Stack id.
        **kwargs: Stack constructor arguments.

    Returns:
        assertions.Template: Synthesized CloudFormation template.
    """
    app = core.App(context={"aws:cdk:bundling-stacks": []})
    return assertions.Template.from_stack(MflOddsPosterStack(app, construct_id, **kwargs))


@pytest.fixture(scope="module")
def prod() -> assertions.Template:
    """Prod stack template."""
    return _synth("MflOddsPosterStack", env_name="prod", league_id=PROD_LEAGUE_ID)


@pytest.fixture(scope="module")
def test_stack() -> assertions.Template:
    """Test stack template (MFL copy league 22744)."""
    return _synth("MflOddsPosterStackTest", env_name="test", league_id="22744")


def _functions(template: assertions.Template) -> dict:
    """Map handler -> Properties for the two app lambdas."""
    return {
        res["Properties"]["Handler"]: res["Properties"]
        for res in template.find_resources("AWS::Lambda::Function").values()
        if res["Properties"].get("Handler") in (POSTER, GATHER)
    }


def test_prod_schedule_fires_wednesday_afternoon_in_season_only(prod: assertions.Template) -> None:
    """Wednesday 22:00 UTC, September through February only (no off-season posts)."""
    prod.has_resource_properties(
        "AWS::Events::Rule",
        {"ScheduleExpression": "cron(0 22 ? 1,2,9-12 4 *)", "State": "ENABLED"},
    )


def test_test_stack_has_no_schedule(test_stack: assertions.Template) -> None:
    """The test stack only runs when CI invokes it."""
    test_stack.resource_count_is("AWS::Events::Rule", 0)


@pytest.mark.parametrize("fixture", ["prod", "test_stack"])
def test_gather_timeout_exceeds_poster_timeout(fixture: str, request: pytest.FixtureRequest) -> None:
    """Gather waits on the poster synchronously, so its timeout must be larger."""
    functions = _functions(request.getfixturevalue(fixture))
    assert {h: p["Timeout"] for h, p in functions.items()} == {POSTER: 30, GATHER: 60}


@pytest.mark.parametrize("fixture", ["prod", "test_stack"])
def test_lambdas_are_arm64_python311(fixture: str, request: pytest.FixtureRequest) -> None:
    """Graviton is cheaper; runtime stays python3.11."""
    for props in _functions(request.getfixturevalue(fixture)).values():
        assert props["Architectures"] == ["arm64"]
        assert props["Runtime"] == "python3.11"


@pytest.mark.parametrize("fixture", ["prod", "test_stack"])
def test_no_public_entry_points_or_paid_secrets(fixture: str, request: pytest.FixtureRequest) -> None:
    """API Gateway, CloudFront and Secrets Manager are gone (cost + exposure)."""
    template = request.getfixturevalue(fixture)
    for resource_type in ("AWS::ApiGateway::RestApi", "AWS::CloudFront::Distribution",
                          "AWS::SecretsManager::Secret", "AWS::S3::Bucket"):
        template.resource_count_is(resource_type, 0)


@pytest.mark.parametrize("fixture", ["prod", "test_stack"])
def test_log_groups_expire_after_30_days(fixture: str, request: pytest.FixtureRequest) -> None:
    """Both lambda log groups have a retention policy."""
    template = request.getfixturevalue(fixture)
    groups = template.find_resources("AWS::Logs::LogGroup")
    assert len(groups) == 2
    assert all(g["Properties"]["RetentionInDays"] == 30 for g in groups.values())


@pytest.mark.parametrize("fixture, league, parameter", [
    ("prod", "15781", "/mfl-odds/prod"),
    ("test_stack", "22744", "/mfl-odds/test"),
])
def test_poster_env_targets_its_own_league_and_config(fixture: str, league: str, parameter: str,
                                                      request: pytest.FixtureRequest) -> None:
    """Each stack posts to its own league and reads its own SSM parameter."""
    functions = _functions(request.getfixturevalue(fixture))
    poster_env = functions[POSTER]["Environment"]["Variables"]
    assert poster_env["LEAGUE_ID"] == league
    assert poster_env["FRANCHISE_ID"] == "0008"
    assert poster_env["CONFIG_PARAMETER_NAME"] == parameter
    assert functions[GATHER]["Environment"]["Variables"]["CONFIG_PARAMETER_NAME"] == parameter


def test_lambdas_can_read_only_their_own_parameter(test_stack: assertions.Template) -> None:
    """Each lambda role may read /mfl-odds/test and nothing else in SSM."""
    statements = [
        stmt
        for policy in test_stack.find_resources("AWS::IAM::Policy").values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
        if "ssm:GetParameter" in (stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]])
    ]
    assert len(statements) == 2
    for stmt in statements:
        rendered = str(stmt["Resource"])
        assert "parameter/mfl-odds/test" in rendered
        assert "prod" not in rendered


def test_function_names_are_exported_for_e2e(test_stack: assertions.Template) -> None:
    """The e2e test finds the lambdas through stack outputs."""
    outputs = test_stack.find_outputs("*")
    assert {"GatherFunctionName", "PosterFunctionName"} <= set(outputs)


def test_non_prod_stack_refuses_prod_league() -> None:
    """A test stack pointed at the real league must fail at synth time."""
    with pytest.raises(ValueError, match="prod league"):
        _synth("MflOddsPosterStackTest", env_name="test", league_id=PROD_LEAGUE_ID)
