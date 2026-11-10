#!/usr/bin/env python3
"""CDK app: prod poster, test poster (MFL copy league), and the CI/OIDC stack."""
import aws_cdk as cdk

from mfl_odds_poster.ci_stack import MflOddsPosterCiStack
from mfl_odds_poster.mfl_odds_poster_stack import MflOddsPosterStack, PROD_LEAGUE_ID

TEST_LEAGUE_ID = "22744"
GITHUB_REPO = "timkelsch/mfl-odds-poster"


def build_app(app: cdk.App) -> cdk.App:
    """Add all stacks to ``app``.

    Args:
        app: CDK app to populate.

    Returns:
        cdk.App: The same app.
    """
    MflOddsPosterStack(app, "MflOddsPosterStack", env_name="prod", league_id=PROD_LEAGUE_ID)
    MflOddsPosterStack(app, "MflOddsPosterStackTest", env_name="test", league_id=TEST_LEAGUE_ID)
    MflOddsPosterCiStack(app, "MflOddsPosterCiStack", repo=GITHUB_REPO)
    return app


if __name__ == "__main__":
    build_app(cdk.App()).synth()
