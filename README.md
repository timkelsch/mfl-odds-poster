# Welcome to your CDK Python project!

This is a blank project for CDK development with Python.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

This project is set up like a standard Python project. The initialization
process also creates a virtualenv within this project, stored under the `.venv`
directory. To create the virtualenv it assumes that there is a `python3`
(or `python` for Windows) executable in your path with access to the `venv`
package. If for any reason the automatic creation of the virtualenv fails,
you can create the virtualenv manually.

To manually create a virtualenv on MacOS and Linux:

```
$ python3 -m venv .venv
```

# Notes on virtual environments

This repo has two python environments - one for CDK and the other for the Python lambda.
Currently, our requirements are that:

- both CDK and the lambda function locally
- the lambda functions on AWS with only the necessary modules installed

As a result, we are running:

- a single virtual env locally that uses root/requirements.txt to
  specify modules for both CDK and the lambda.
- a requirements.txt file in lambda directory that contains only the modules for the lambda

In the future, if the benefits became worth the cost of implementation and ongoing overhead,
we could have two virtual environments in the repo root directory - one for CDK and another for
the lambda. This would require switching virtual envs whenever the dev switches focus from CDK
to lambda and vice versa.

# Long Term Storage Opportunities

1. API Host
1. NFL year start date

# Config (SSM Parameter Store)

Both stacks read one SecureString parameter, `/mfl-odds` (free `aws/ssm` key). Prod and the
copy league are owned by the same MFL login, so there is one password in one place.
CloudFormation can't create SecureStrings, so it's created once by hand:

```
{
  "the-odds-api-key": "",
  "mfl-username": "",
  "mfl-password": "",
  "nfl-api-key": ""
}
```


# Stacks

| Stack | League | Schedule | Deployed by |
|---|---|---|---|
| `MflOddsPosterStack` | 15781 (prod) | Wed 22:00 UTC, Sep-Feb | CI, on merge to `main` after e2e passes |
| `MflOddsPosterStackTest` | 22744 (MFL copy league) | none | CI, on every PR and push to `main` |
| `MflOddsPosterCiStack` | - | - | by hand, once (GitHub OIDC role) |

# Tests

All changes are test-driven: write the failing test first.

- `pytest` runs the unit tests (no network).
- `pytest -m e2e` deploys nothing. It invokes the already-deployed test stack, which posts to
  copy league 22744, then reads the 22744 message board and checks that the post matches.
  Run it locally with `AWS_PROFILE=pmfl pytest -m e2e` after
  `cdk deploy MflOddsPosterStackTest`.
  It refuses to run unless the deployed poster targets league 22744.
  "Notify on new message board post" is turned off for every team in the copy league.

# CI/CD (`.github/workflows/ci-cd.yaml`)

`test` (lint, unit, synth) -> `e2e` (deploy test stack, run e2e) -> `deploy-prod` (main only).
AWS access is through GitHub OIDC, assuming the `mfl-odds-poster-ci` role (fixed name, ARN hardcoded in `ci-cd.yaml`; no repo variables or secrets).

# Env of Notes

After the init process completes and the virtualenv is created, you can use the following
step to activate your virtualenv.

```
$ source .venv/bin/activate
```

If you are a Windows platform, you would activate the virtualenv like this:

```
% .venv\Scripts\activate.bat
```

Once the virtualenv is activated, you can install the required dependencies.

```
$ pip install -r requirements.txt
```

At this point you can now synthesize the CloudFormation template for this code.

```
$ cdk synth
```

To add additional dependencies, for example other CDK libraries, just add
them to your `setup.py` file and rerun the `pip install -r requirements.txt`
command.

## Useful commands

- `cdk ls` list all stacks in the app
- `cdk synth` emits the synthesized CloudFormation template
- `cdk deploy` deploy this stack to your default AWS account/region
- `cdk diff` compare deployed stack with current state
- `cdk docs` open CDK documentation

Enjoy!

### One-time cleanup after the first lean prod deploy

```
.venv/bin/python scripts/cleanup_old_prod.py           # dry run: shows what would go
.venv/bin/python scripts/cleanup_old_prod.py --apply   # deletes it
```

Removes the old CloudFront log buckets and old lambda/API log groups the previous stack left behind, and closes the
Dependabot PRs superseded by #11. It refuses to run until `MflOddsPosterStack` is `UPDATE_COMPLETE` with the new
lambdas and none of the old resources, and skips anything a live stack still manages.
