"""The CDK app wires up prod, test and CI stacks."""
import aws_cdk as core

import app as cdk_app


def test_app_defines_prod_test_and_ci_stacks() -> None:
    """Stack ids are what the workflow deploys by name."""
    application = cdk_app.build_app(core.App(context={"aws:cdk:bundling-stacks": []}))
    names = {child.node.id for child in application.node.children if isinstance(child, core.Stack)}
    assert names == {"MflOddsPosterStack", "MflOddsPosterStackTest", "MflOddsPosterCiStack"}


def test_test_stack_targets_copy_league() -> None:
    """The test stack posts to MFL copy league 22744."""
    assert cdk_app.TEST_LEAGUE_ID == "22744"
