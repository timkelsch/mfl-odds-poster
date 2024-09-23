from aws_solutions_constructs.aws_cloudfront_apigateway_lambda import CloudFrontToApiGatewayToLambda
from aws_cdk import (
    Fn,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_secretsmanager,
    aws_kms,
    Stack
)
from constructs import Construct
import os
import subprocess


class MflOddsPosterStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        mfl_odds_lambda_role = iam.Role(
            self,
            "MyLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )

        mfl_odds_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[Fn.sub("arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/*")],
                effect=iam.Effect.ALLOW
            )
        )

        mfl_odds_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["secretsmanager:GetSecretValue"],
                resources=[Fn.sub("arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:MflOddsPosterStack-CloudFrontApiGatewayToLambdaLam*")]
            )
        )

        mfl_odds_kms_key = aws_kms.CfnKey(
            self,
            "mflOddsKmsKey",
            bypass_policy_lockout_safety_check=False,
            enable_key_rotation=True,
            enabled=True,
            key_policy={
                "Version": "2012-10-17",
                "Id": "key-default-1",
                "Statement": [
                    {
                        "Sid": "Enable IAM User Permissions",
                        "Effect": "Allow",
                        "Principal": {
                            "AWS": Fn.sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root")
                        },
                        "Action": "kms:*",
                        "Resource": "*"
                    },
                    {
                        "Sid": "Allow use of the key",
                        "Effect": "Allow",
                        "Principal": {
                            "AWS": mfl_odds_lambda_role.role_arn
                        },
                        "Action": [
                            "kms:DescribeKey",
                            "kms:Encrypt",
                            "kms:Decrypt",
                            "kms:ReEncrypt*",
                            "kms:GenerateDataKey",
                            "kms:GenerateDataKeyWithoutPlaintext"
                        ],
                        "Resource": "*"
                    }
                ]
            },
            multi_region=False,
            rotation_period_in_days=360,
        )

        mfl_odds_secret = aws_secretsmanager.CfnSecret(
            self,
            "mflOdds-ApiKey",
            description="api key for the-odds-api",
            kms_key_id=mfl_odds_kms_key.attr_key_id,
            name="mflOdds-ApiKey",
            # secret_string='l12345bno1'  # placeholder - manually replace with real secret after deploy
        )

        mfl_odds_secret_resource_policy = aws_secretsmanager.CfnResourcePolicy(
            self,
            "mflOddsSecretResourcePolicy",
            block_public_policy=True,
            resource_policy={
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": Fn.sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root")
                    },
                    "Action": "secretsmanager:*",
                    "Resource": "*"
                }, {
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": mfl_odds_lambda_role.role_arn
                    },
                    "Action": [
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:Get*",
                        "secretsmanager:List*"
                    ],
                    "Resource": mfl_odds_secret.attr_id
                }]
            },  # Required
            secret_id=mfl_odds_secret.attr_id  # Required
        )

        CloudFrontToApiGatewayToLambda(
            self, 'CloudFrontApiGatewayToLambda',
            lambda_function_props=_lambda.FunctionProps(
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset(
                    'mfl_odds',
                    exclude=['.envrc', 'games.json']
                ),
                handler='gather.lambda_handler',
                layers=[self.create_dependencies_layer('mfl_odds', 'gather')],
                role=mfl_odds_lambda_role,
                environment={
                    'SECRET_ARN': mfl_odds_secret.attr_id
                }
            ),
            # NOTE - we use RestApiProps here because the actual type,
            # LambdaRestApiProps requires the handler function which does
            # not yet exist. As RestApiProps is a subset of of
            # LambdaRestApiProps (although does not *extend* that interface)
            # this works fine when the props object reaches the
            # underlying TypeScript code that implements Constructs
            api_gateway_props=apigw.RestApiProps(
                default_method_options=apigw.MethodOptions(
                    authorization_type=apigw.AuthorizationType.NONE
                )
            )
        )

    def create_dependencies_layer(
            self,
            project_name,
            function_name: str) -> _lambda.LayerVersion:
        requirements_file = "mfl_odds/requirements.txt"  # 👈🏽 point to requirements.txt
        output_dir = ".build/app"  # 👈🏽 a temp directory to store the dependencies

        if not os.environ.get("SKIP_PIP"):
            # 👇🏽 download the dependencies and store them in the output_dir
            subprocess.check_call(
                f"pip install -r {requirements_file} -t {output_dir}/python".split()
            )

        layer_id = f"{project_name}-{function_name}-dependencies"  # 👈🏽 a unique id for the layer
        layer_code = _lambda.Code.from_asset(output_dir)  # 👈🏽 import the dependencies / code

        my_layer = _lambda.LayerVersion(
            self,
            layer_id,
            code=layer_code,
        )

        return my_layer
