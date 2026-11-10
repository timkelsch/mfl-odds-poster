"""Unit tests for the GitHub Actions OIDC stack."""
import json
from pathlib import Path

import aws_cdk as core
import aws_cdk.assertions as assertions
import pytest

from mfl_odds_poster.ci_stack import MflOddsPosterCiStack

REPO = "timkelsch/mfl-odds-poster"


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """CI stack template."""
    app = core.App()
    return assertions.Template.from_stack(MflOddsPosterCiStack(app, "MflOddsPosterCiStack", repo=REPO))


def _statements(template: assertions.Template) -> list[dict]:
    """All identity-policy statements attached to the CI role."""
    return [
        stmt
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
    ]


def _actions(stmt: dict) -> list[str]:
    """Normalize a statement's Action to a list."""
    return stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]]


def test_creates_github_oidc_provider(template: assertions.Template) -> None:
    """The account has no GitHub provider yet, so the stack owns it."""
    template.has_resource_properties("Custom::AWSCDKOpenIdConnectProvider", {
        "Url": "https://token.actions.githubusercontent.com",
        "ClientIDList": ["sts.amazonaws.com"],
    })


def test_role_trusts_only_this_repo_main_and_prs(template: assertions.Template) -> None:
    """Only main-branch pushes and PRs of this repo can assume the role."""
    roles = template.find_resources("AWS::IAM::Role", {
        "Properties": {"AssumeRolePolicyDocument": {"Statement": [
            {"Action": "sts:AssumeRoleWithWebIdentity"}]}}})
    (role,) = roles.values()
    condition = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]
    assert condition["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert sorted(condition["StringLike"]["token.actions.githubusercontent.com:sub"]) == sorted([
        f"repo:{REPO}:ref:refs/heads/main",
        f"repo:{REPO}:pull_request",
    ])


def test_role_can_assume_cdk_bootstrap_roles(template: assertions.Template) -> None:
    """cdk deploy runs through the bootstrap roles."""
    stmts = [s for s in _statements(template) if "sts:AssumeRole" in _actions(s)]
    assert len(stmts) == 1
    assert "role/cdk-hnb659fds-*" in json.dumps(stmts[0]["Resource"])


def test_role_reaches_only_test_stack_runtime_resources(template: assertions.Template) -> None:
    """Invoke/read is scoped to the test stack and the shared login parameter, never prod lambdas."""
    rendered = json.dumps([s for s in _statements(template) if "sts:AssumeRole" not in _actions(s)])
    assert "function:MflOddsPosterStackTest-*" in rendered
    assert "parameter/mfl-odds\"" in rendered
    assert "stack/MflOddsPosterStackTest/*" in rendered
    assert "function:MflOddsPosterStack-" not in rendered


def test_role_arn_is_exported(template: assertions.Template) -> None:
    """The workflow needs the role ARN."""
    assert "CiRoleArn" in template.find_outputs("*")


def test_role_has_fixed_name(template: assertions.Template) -> None:
    """A fixed name makes the ARN predictable, so the workflow can hardcode it."""
    template.has_resource_properties("AWS::IAM::Role", {"RoleName": "mfl-odds-poster-ci"})


def test_workflow_assumes_the_fixed_role_without_repo_variables() -> None:
    """No manual GitHub variable: the role ARN lives in the workflow file."""
    workflow = (Path(__file__).parents[2] / ".github/workflows/ci-cd.yaml").read_text()
    assert "vars.AWS_ROLE_ARN" not in workflow
    assert workflow.count("role-to-assume: arn:aws:iam::287140326780:role/mfl-odds-poster-ci") == 2


def test_workflow_actions_are_on_node24_majors() -> None:
    """Node 20 actions are deprecated on GitHub runners; pin the Node 24 majors."""
    import re
    workflow = (Path(__file__).parents[2] / ".github/workflows/ci-cd.yaml").read_text()
    minimum = {"actions/checkout": 7, "actions/setup-python": 7, "actions/setup-node": 7,
               "aws-actions/configure-aws-credentials": 6}
    uses = re.findall(r"uses:\s*([\w./-]+)@v(\d+)", workflow)
    assert uses
    for action, major in uses:
        assert int(major) >= minimum[action], f"{action}@v{major} is below v{minimum[action]}"
