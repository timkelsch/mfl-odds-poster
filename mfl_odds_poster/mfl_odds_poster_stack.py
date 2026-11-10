"""Odds poster stack: gather lambda -> poster lambda, on a weekly in-season schedule."""
from aws_cdk import (
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    BundlingOptions,
    CfnOutput,
    Duration,
    Stack,
)
from constructs import Construct

PROD_LEAGUE_ID = "15781"
FRANCHISE_ID = "0008"
# One MFL login owns both leagues, so prod and test share one parameter.
CONFIG_PARAMETER = "/mfl-odds"
RUNTIME = _lambda.Runtime.PYTHON_3_11
ARCHITECTURE = _lambda.Architecture.ARM_64


def _code(path: str, exclude: list[str] | None = None) -> _lambda.Code:
    """Bundle a lambda directory with its requirements for arm64.

    Args:
        path: Lambda source directory.
        exclude: Glob patterns to leave out of the asset.

    Returns:
        _lambda.Code: Asset code.
    """
    return _lambda.Code.from_asset(
        path,
        exclude=["__pycache__", *(exclude or [])],
        bundling=BundlingOptions(
            image=RUNTIME.bundling_image,
            platform="linux/arm64",
            command=["bash", "-c",
                     "pip install --no-cache-dir -r requirements.txt -t /asset-output && cp -r . /asset-output"],
        ),
    )


class MflOddsPosterStack(Stack):
    """Gather + poster lambdas for one MFL league.

    Args:
        scope: CDK scope.
        construct_id: Stack id.
        env_name: ``prod`` or ``test``. Only prod gets a schedule.
        league_id: MFL league to post to.
        **kwargs: Passed to :class:`aws_cdk.Stack`.

    Raises:
        ValueError: If a non-prod stack is pointed at the prod league.
    """

    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, league_id: str,
                 **kwargs) -> None:
        if env_name != "prod" and league_id == PROD_LEAGUE_ID:
            raise ValueError(f"{env_name} stack must never target the prod league {PROD_LEAGUE_ID}")
        super().__init__(scope, construct_id, **kwargs)

        parameter_name = CONFIG_PARAMETER
        # SecureString parameters cannot be created by CloudFormation; created once by hand.
        parameter_arn = self.format_arn(service="ssm", resource="parameter",
                                        resource_name=parameter_name.lstrip("/"))

        read_config = iam.PolicyStatement(actions=["ssm:GetParameter"], resources=[parameter_arn])

        poster = _lambda.Function(
            self, "PosterFunction",
            runtime=RUNTIME,
            architecture=ARCHITECTURE,
            code=_code("lambda/post_odds", exclude=["nfl-schedule.json"]),
            handler="post.lambda_handler",
            # login + host lookup + season API + post, each with retries
            timeout=Duration.seconds(30),
            environment={
                "CONFIG_PARAMETER_NAME": parameter_name,
                "LEAGUE_ID": league_id,
                "FRANCHISE_ID": FRANCHISE_ID,
            },
            log_group=logs.LogGroup(self, "PosterLogs", retention=logs.RetentionDays.ONE_MONTH),
            # never re-run after a failure: the post may already be on the board
            retry_attempts=0,
        )

        gather = _lambda.Function(
            self, "GatherFunction",
            runtime=RUNTIME,
            architecture=ARCHITECTURE,
            code=_code("lambda/gather_odds", exclude=[".envrc", "games.json"]),
            handler="gather.lambda_handler",
            # invokes the poster synchronously, so must exceed its timeout
            timeout=Duration.seconds(60),
            environment={
                "CONFIG_PARAMETER_NAME": parameter_name,
                "POSTER_LAMBDA_ARN": poster.function_arn,
            },
            log_group=logs.LogGroup(self, "GatherLogs", retention=logs.RetentionDays.ONE_MONTH),
            # EventBridge invokes async; a retry after the poster succeeded would double-post
            retry_attempts=0,
        )
        poster.add_to_role_policy(read_config)
        gather.add_to_role_policy(read_config)
        poster.grant_invoke(gather)

        if env_name == "prod":
            rule = events.Rule(
                self, "MyRule",
                # 22:00 UTC Wednesdays (15:00 PT), before any Wed/Thu kickoff.
                # Months 9-12 and 1-2 only: no empty off-season posts.
                schedule=events.Schedule.cron(minute="0", hour="22", month="1,2,9-12",
                                              week_day="4", year="*"),
            )
            rule.add_target(targets.LambdaFunction(gather))

        CfnOutput(self, "GatherFunctionName", value=gather.function_name)
        CfnOutput(self, "PosterFunctionName", value=poster.function_name)
