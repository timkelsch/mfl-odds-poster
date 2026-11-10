"""Safety logic of the one-time post-migration cleanup script."""
import pytest

from scripts import cleanup_old_prod as cleanup

NEW_PROD = [
    ("AWS::Lambda::Function", "PosterFunctionFECAE2BD"),
    ("AWS::Lambda::Function", "GatherFunction5B0B6E41"),
    ("AWS::Events::Rule", "MyRuleA44AB831"),
]


@pytest.mark.parametrize("name", [
    "mfloddsposterstack-cloudfrontapigatewaytolambdaclo-1pnjhfj7enxz",
    "mfloddsposterstack-cloudfrontapigatewaytolambdaclo-kmuwxx7s70yq",
])
def test_old_cloudfront_log_buckets_are_targeted(name: str) -> None:
    assert cleanup.is_old_bucket(name)


@pytest.mark.parametrize("name", ["cdk-hnb659fds-assets-287140326780-us-east-1", "mfl-scoring-data",
                                  "mfloddsposterstacktest-anything"])
def test_other_buckets_are_never_targeted(name: str) -> None:
    assert not cleanup.is_old_bucket(name)


@pytest.mark.parametrize("name", [
    "/aws/lambda/MflOddsPosterStack-ApiGatewayToLambdaPatternLambda-rWJzEWrFSI9Z",
    "/aws/lambda/MflOddsPosterStack-CloudFrontApiGatewayToLambdaLam-kacTvNuC8nEv",
    "MflOddsPosterStack-CloudFrontApiGatewayToLambdaApiAccessLogGroup2FD9EE65-4SaMLewR5Ptv",
    "MflOddsPosterStack-ApiGatewayToLambdaPatternApiAccessLogGroup9383E9FC-EafVApqnsq0I",
])
def test_old_log_groups_are_targeted(name: str) -> None:
    assert cleanup.is_old_log_group(name)


@pytest.mark.parametrize("name", [
    "MflOddsPosterStack-PosterLogsB9BD078D-abc",            # new prod
    "MflOddsPosterStack-GatherLogsE6857C36-abc",            # new prod
    "MflOddsPosterStackTest-GatherLogsE6857C36-j3FASKSzAWqg",
    "/aws/lambda/MflOddsPosterStackTest-ApiGatewayToLambdaX",
    "/aws/lambda/MflOddsPosterCiStack-CustomAWSCDKOpenIdConnectProv-y2x3T7ETxnl2",
    "/aws/lambda/mfl-scoring-ApiGatewayToLambda",
])
def test_new_test_ci_and_other_log_groups_are_never_targeted(name: str) -> None:
    assert not cleanup.is_old_log_group(name)


def test_select_skips_anything_a_live_stack_still_manages() -> None:
    names = ["MflOddsPosterStack-CloudFrontApiGatewayToLambdaApiAccessLogGroup-a",
             "MflOddsPosterStack-CloudFrontApiGatewayToLambdaApiAccessLogGroup-b"]
    managed = {"MflOddsPosterStack-CloudFrontApiGatewayToLambdaApiAccessLogGroup-a"}
    assert cleanup.select(names, cleanup.is_old_log_group, managed) == [names[1]]


def test_preflight_passes_once_new_prod_is_deployed() -> None:
    assert cleanup.preflight("UPDATE_COMPLETE", NEW_PROD) == []


@pytest.mark.parametrize("status", ["UPDATE_IN_PROGRESS", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_FAILED"])
def test_preflight_blocks_unless_prod_update_completed(status: str) -> None:
    assert cleanup.preflight(status, NEW_PROD)


@pytest.mark.parametrize("leftover", [
    ("AWS::CloudFront::Distribution", "CloudFrontApiGatewayToLambdaCloudFrontToApiGatewayCloudFrontDistributionE7"),
    ("AWS::SecretsManager::Secret", "mflOddsApiKey"),
    ("AWS::ApiGateway::RestApi", "ApiGatewayToLambdaPatternLambdaRestApiC0598E46"),
])
def test_preflight_blocks_while_old_prod_resources_remain(leftover: tuple[str, str]) -> None:
    assert cleanup.preflight("UPDATE_COMPLETE", [*NEW_PROD, leftover])


def test_preflight_blocks_if_new_lambdas_missing() -> None:
    assert cleanup.preflight("UPDATE_COMPLETE", [("AWS::Events::Rule", "MyRuleA44AB831")])
