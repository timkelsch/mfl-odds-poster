"""Dependency policy: only what the code imports, pinned to patch with ``~=``."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)~=(?P<version>\d+\.\d+\.\d+(\.post\d+)?)$")

# Direct imports only; boto3 in the lambdas comes from the Lambda runtime.
EXPECTED = {
    "requirements.txt": {"aws-cdk-lib", "constructs", "boto3", "requests", "pytz", "python-dateutil"},
    "requirements-dev.txt": {"pytest", "flake8"},
    "lambda/gather_odds/requirements.txt": {"requests", "pytz", "python-dateutil"},
    "lambda/post_odds/requirements.txt": {"requests"},
}

# Lowest versions that clear the open Dependabot alerts.
MINIMUM = {"requests": (2, 33, 0), "aws-cdk-lib": (2, 253, 0), "pytest": (9, 0, 3)}


def _pins(path: str) -> dict[str, str]:
    lines = [ln.strip() for ln in (ROOT / path).read_text().splitlines()]
    pins = {}
    for line in filter(None, lines):
        match = PIN.match(line)
        assert match, f"{path}: '{line}' is not pinned as name~=X.Y.Z"
        pins[match["name"]] = match["version"]
    return pins


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_only_used_packages_pinned_to_patch(path: str) -> None:
    """Every line is ``name~=X.Y.Z`` and nothing unused is listed."""
    assert set(_pins(path)) == EXPECTED[path]


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_pins_clear_known_vulnerabilities(path: str) -> None:
    """No pin sits below the version that fixes its Dependabot alert."""
    for name, version in _pins(path).items():
        if name in MINIMUM:
            assert tuple(int(p) for p in version.split(".")[:3]) >= MINIMUM[name], f"{path}: {name} {version}"


def test_cdk_cli_matches_library_era() -> None:
    """The workflow's CDK CLI must be new enough for aws-cdk-lib's cloud assembly."""
    workflow = (ROOT / ".github/workflows/ci-cd.yaml").read_text()
    assert 'CDK_VERSION: "2.1148.0"' in workflow
