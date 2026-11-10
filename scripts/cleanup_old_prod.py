"""One-time cleanup after the first prod deploy of the lean (SSM, no API Gateway) stack.

Dry run by default; nothing is changed without ``--apply``.

    .venv/bin/python scripts/cleanup_old_prod.py            # show the plan
    .venv/bin/python scripts/cleanup_old_prod.py --apply    # do it

Deletes only what the old stack left behind (CloudFormation kept these with
DeletionPolicy=Retain, or Lambda created them outside the stack):
  * the old CloudFront access-log S3 buckets
  * the old lambdas' and API Gateways' log groups
Then closes the stale Dependabot PRs that PR #11 superseded.

Refuses to run unless the prod stack update completed and no old prod resource
remains in it. Never touches anything a live CloudFormation stack manages, the
test stack, the CI stack or the new prod resources. Never invokes a lambda.
"""
import argparse
import json
import subprocess
import sys
from typing import Callable, Iterable

PROD_STACK = "MflOddsPosterStack"
REPO = "timkelsch/mfl-odds-poster"
SUPERSEDING_PR = 11
STALE_DEPENDABOT_PRS = (4, 5, 9, 10)
OLD_BUCKET_PREFIX = "mfloddsposterstack-cloudfrontapigatewaytolambdaclo-"
OLD_RESOURCE_TYPES = {
    "AWS::CloudFront::Distribution",
    "AWS::ApiGateway::RestApi",
    "AWS::SecretsManager::Secret",
}
NEW_LAMBDA_PREFIXES = ("PosterFunction", "GatherFunction")


def is_old_bucket(name: str) -> bool:
    """Whether ``name`` is one of the old CloudFront access-log buckets."""
    return name.startswith(OLD_BUCKET_PREFIX)


def is_old_log_group(name: str) -> bool:
    """Whether ``name`` belongs to the old prod lambdas or API Gateways.

    Matches only ``MflOddsPosterStack-`` (prod, not ``...StackTest`` or
    ``...CiStack``) names that come from the old ApiGatewayToLambda constructs.
    """
    bare = name.removeprefix("/aws/lambda/")
    return bare.startswith(f"{PROD_STACK}-") and "ApiGatewayToLambda" in bare


def select(names: Iterable[str], predicate: Callable[[str], bool], managed: set[str]) -> list[str]:
    """Names matching ``predicate`` that no live stack still manages."""
    return sorted(n for n in names if predicate(n) and n not in managed)


def preflight(status: str, resources: list[tuple[str, str]]) -> list[str]:
    """Reasons the cleanup must not run yet (empty list = safe).

    Args:
        status: Prod stack status.
        resources: ``(type, logical_id)`` of every resource in the prod stack.
    """
    problems = []
    if status != "UPDATE_COMPLETE":
        problems.append(f"{PROD_STACK} status is {status}, expected UPDATE_COMPLETE")
    leftovers = [lid for rtype, lid in resources if rtype in OLD_RESOURCE_TYPES]
    if leftovers:
        problems.append(f"old prod resources still in the stack: {leftovers}")
    lambdas = [lid for rtype, lid in resources if rtype == "AWS::Lambda::Function"]
    for prefix in NEW_LAMBDA_PREFIXES:
        if not any(lid.startswith(prefix) for lid in lambdas):
            problems.append(f"new {prefix} missing from {PROD_STACK}")
    return problems


def _managed_physical_ids(cfn) -> set[str]:
    """Physical IDs of every resource in every live stack in the region."""
    ids = set()
    for page in cfn.get_paginator("list_stacks").paginate():
        for stack in page["StackSummaries"]:
            if stack["StackStatus"] == "DELETE_COMPLETE":
                continue
            for rpage in cfn.get_paginator("list_stack_resources").paginate(StackName=stack["StackId"]):
                ids.update(r.get("PhysicalResourceId", "") for r in rpage["StackResourceSummaries"])
    return ids


def _empty_and_delete_bucket(s3, name: str) -> None:
    """Delete every object version and delete marker, then the bucket."""
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=name):
        keys = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in page.get("Versions", []) + page.get("DeleteMarkers", [])]
        if keys:
            s3.delete_objects(Bucket=name, Delete={"Objects": keys, "Quiet": True})
    s3.delete_bucket(Bucket=name)


def _gh(*args: str) -> str:
    """Run gh as the personal account that owns the repo."""
    token = subprocess.run(["gh", "auth", "token", "-u", "timkelsch"], check=True,
                           capture_output=True, text=True).stdout.strip()
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                          env={"GH_TOKEN": token, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
                          ).stdout


def main() -> int:
    """Plan the cleanup, and apply it with ``--apply``."""
    import boto3  # imported here so the unit tests don't need AWS

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--profile", default="pmfl")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn, s3, logs = (session.client(s) for s in ("cloudformation", "s3", "logs"))

    stack = cfn.describe_stacks(StackName=PROD_STACK)["Stacks"][0]
    resources = [(r["ResourceType"], r["LogicalResourceId"])
                 for page in cfn.get_paginator("list_stack_resources").paginate(StackName=PROD_STACK)
                 for r in page["StackResourceSummaries"]]
    problems = preflight(stack["StackStatus"], resources)
    if problems:
        print("NOT SAFE TO CLEAN UP YET:", *problems, sep="\n  ")
        return 1

    managed = _managed_physical_ids(cfn)
    buckets = select((b["Name"] for b in s3.list_buckets()["Buckets"]), is_old_bucket, managed)
    groups = select((g["logGroupName"] for page in logs.get_paginator("describe_log_groups").paginate()
                     for g in page["logGroups"]), is_old_log_group, managed)

    pr = json.loads(_gh("pr", "view", str(SUPERSEDING_PR), "-R", REPO, "--json", "state"))
    prs = []
    for number in STALE_DEPENDABOT_PRS:
        info = json.loads(_gh("pr", "view", str(number), "-R", REPO, "--json", "state,author"))
        if info["state"] == "OPEN" and info["author"]["login"] == "app/dependabot":
            prs.append(number)

    mode = "APPLY" if args.apply else "DRY RUN (add --apply to delete)"
    print(f"== {mode}  profile={args.profile}")
    print(f"S3 buckets to empty + delete ({len(buckets)}):", *buckets, sep="\n  ")
    print(f"Log groups to delete ({len(groups)}):", *groups, sep="\n  ")
    print(f"Dependabot PRs to close ({len(prs)}):", *prs, sep="\n  ")
    if pr["state"] != "MERGED":
        print(f"  (skipped: PR #{SUPERSEDING_PR} is {pr['state']}, not MERGED)")

    if not args.apply:
        return 0
    for name in buckets:
        _empty_and_delete_bucket(s3, name)
        print("deleted bucket", name)
    for name in groups:
        logs.delete_log_group(logGroupName=name)
        print("deleted log group", name)
    if pr["state"] == "MERGED":
        for number in prs:
            _gh("pr", "close", str(number), "-R", REPO, "--delete-branch",
                "--comment", f"Superseded by #{SUPERSEDING_PR}, which moved to ~= pins at current versions.")
            print("closed PR", number)
    return 0


if __name__ == "__main__":
    sys.exit(main())
