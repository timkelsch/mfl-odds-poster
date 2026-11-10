"""GitHub Actions OIDC provider + deploy/e2e role. Deployed once by hand, not by CI."""
from aws_cdk import ArnFormat, CfnOutput, Duration, Stack, aws_iam as iam
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
TEST_STACK_NAME = "MflOddsPosterStackTest"
CONFIG_PARAMETER = "mfl-odds"  # shared login; same password as prod either way
CI_ROLE_NAME = "mfl-odds-poster-ci"  # fixed so .github/workflows/ci-cd.yaml can hardcode the ARN


class MflOddsPosterCiStack(Stack):
    """OIDC role that CI uses to deploy both stacks and run the e2e test.

    Args:
        scope: CDK scope.
        construct_id: Stack id.
        repo: ``owner/name`` of the GitHub repository allowed to assume the role.
        **kwargs: Passed to :class:`aws_cdk.Stack`.
    """

    def __init__(self, scope: Construct, construct_id: str, *, repo: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OpenIdConnectProvider(
            self, "GitHubOidc", url=GITHUB_OIDC_URL, client_ids=["sts.amazonaws.com"])

        role = iam.Role(
            self, "CiRole",
            role_name=CI_ROLE_NAME,
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {"token.actions.githubusercontent.com:sub": [
                        f"repo:{repo}:ref:refs/heads/main",
                        f"repo:{repo}:pull_request",
                    ]},
                },
            ),
        )

        # cdk deploy (both stacks) goes through the bootstrap roles.
        role.add_to_policy(iam.PolicyStatement(
            actions=["sts:AssumeRole"],
            resources=[self.format_arn(service="iam", region="", resource="role",
                                       resource_name="cdk-hnb659fds-*")],
        ))
        # e2e: test stack only.
        role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction", "lambda:GetFunctionConfiguration"],
            resources=[self.format_arn(service="lambda", resource="function",
                                       resource_name=f"{TEST_STACK_NAME}-*",
                                       arn_format=ArnFormat.COLON_RESOURCE_NAME)],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name=CONFIG_PARAMETER)],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=["cloudformation:DescribeStacks"],
            resources=[self.format_arn(service="cloudformation", resource="stack",
                                       resource_name=f"{TEST_STACK_NAME}/*")],
        ))

        CfnOutput(self, "CiRoleArn", value=role.role_arn)
