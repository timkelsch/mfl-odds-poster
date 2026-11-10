# Plan: dev environment, then dependency fixes

Status: Part 1 superseded (2026-11-09) by the test stack + e2e + CI/CD described in the README.
Part 2 not started (planned 2026-10-14).

## Why

There's no test environment, and breaking the weekly post is costly. MyFantasyLeague has
no sandbox: every API "Test it!" link calls production. Everything that has actually broken
this project (deleted KMS key, expired secret, lapsed RapidAPI, MFL `<error>` responses)
happens before the final message board post. A dry-run dev stack can exercise all of that
in real AWS without posting.

## Part 1: dev environment

1. **Make the MFL target configurable.** `lambda/post_odds/post.py` hardcodes
   `LEAGUE_ID = "15781"` and `FRANCHISE_ID = "0008"`. Move these, plus the MFL host, into
   Lambda environment variables, and keep the current values as prod defaults.
2. **Add a `DRY_RUN` flag.** When it's true, the poster does everything except the
   message board import and logs the subject and body instead. Add unit tests for both modes.
3. **Add a dev CDK stack** (`MflOddsPosterStack-Dev`) in `app.py`:
   - no EventBridge schedule (invoke by hand only)
   - `DRY_RUN=true` by default
   - its own secret, so a dev deploy can never touch the prod secret or its KMS key
4. **Workflow for every change:** deploy to dev, invoke the gather Lambda by hand, read the
   logged post, run `cdk diff` against prod, then deploy to prod.
5. **Optional:** point dev at a free preseason MFL test league to test real posts. Ask MFL
   support first whether test leagues are allowed and what the current free terms are.
6. **Fix CI** (`.github/workflows/.github-actions.yaml`). Today it's dangerous:
   - The job named `diff` actually runs `cdk deploy --require-approval never` on every push
     and PR.
   - The `if:` on the `deploy` step is a multi-line `${{ }}` string, so it always
     evaluates to true.
   - It only does nothing now because the jobs never check out the code, so every run fails.
   - Rewrite it to run the tests and `cdk synth`/`diff` only (or deploy to dev). Add a
     `permissions:` block. Keep prod deploys manual.

## Part 2: dependency (Dependabot) fixes

As of 2026-10-14 there are 26 open Dependabot alerts across 6 packages, and no code
scanning or secret scanning alerts.

| Package | Fixed in | Risk |
|---|---|---|
| urllib3 | 2.8.0 | Low (Lambda runtime) |
| requests | 2.33.0 | Low (Lambda runtime) |
| idna | 3.15 | Low |
| setuptools | 83.0.0 | Low (build-time only) |
| pytest | 9.0.3 | Probably stale: already on 9.1.1 |
| aws-cdk-lib | 2.253.0 | Medium: do it separately, after reading a `cdk diff` |

Notes:
- Alerts on urllib3, idna and setuptools point at `lambda/gather_odds/requirements.txt`,
  where they're pulled in indirectly through requests. Pin them explicitly to close the alerts.
- Check the Lambda Python runtime (currently python3.11) against the new versions'
  minimum supported Python first.
- Stale Dependabot PRs #4, #5, #9 and #10 and the old PR #3 can be closed once this lands.
- A CDK upgrade plus deploy is what deleted the KMS key in May 2026. Before any prod
  deploy, check the diff for `AWS::KMS::Key` deletion or `AWS::SecretsManager::Secret`
  replacement.
- Deploy right after a Wednesday run (cron fires Wednesday 22:00 UTC) so there are about
  6 days to catch problems.

## Also worth doing

- Add a CloudWatch alarm on gather-Lambda errors. A silent failure went unnoticed for
  4 months.
- The EventBridge rule fires year-round, so it posts empty messages in the off-season.
- Move the secret to SSM Parameter Store. This is part of the cost plan, and it's easiest to
  do while the dev stack exists.
