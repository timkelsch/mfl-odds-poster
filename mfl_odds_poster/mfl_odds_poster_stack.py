from aws_solutions_constructs.aws_cloudfront_apigateway_lambda import CloudFrontToApiGatewayToLambda
from aws_cdk import (
  aws_lambda as _lambda,
  aws_apigateway as apigw,
  aws_secretsmanager,
  aws_kms,
  CfnTag,
  Stack
)
from constructs import Construct
import os, subprocess

class MflOddsPosterStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        mfl_odds_kms_key = aws_kms.CfnKey(self, "mflOddsKmsKey",
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
                            "AWS": "arn:aws:iam::287140326780:root"
                        },
                        "Action": "kms:*",
                        "Resource": "*"
                    },
                    {
                        "Sid": "Allow use of the key",
                        "Effect": "Allow",
                        "Principal": {
                            "AWS": "arn:aws:iam::287140326780:role/mfl-scoring-MflScoringFunctionIamRole-7qqNIqgCXaLz"
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
            # origin="AWS_KMS",
            rotation_period_in_days=360,
        )
        
        mfl_odds_secret = aws_secretsmanager.CfnSecret(self, "mflOddsApiKey",
            description="api key for the-odds-api",
            kms_key_id=mfl_odds_kms_key.attr_key_id,
            name="mflOddsApiKey",
            secret_string='l12345bno134tipjknwertqghiwerfauyigk'
        )

        mfl_odds_secret_resource_policy = aws_secretsmanager.CfnResourcePolicy(self, "mflOddsSecretResourcePolicy",
            block_public_policy=False,
            resource_policy={
                "Version" : "2012-10-17",
                "Statement" : [ {
                    "Effect" : "Allow",
                    "Principal" : {
                    "AWS" : "arn:aws:iam::287140326780:root"
                    },
                    "Action" : "secretsmanager:*",
                    "Resource" : "*"
                }, {
                    "Effect" : "Allow",
                    "Principal" : {
                    "AWS" : "arn:aws:iam::287140326780:role/mfl-scoring-MflScoringFunctionIamRole-7qqNIqgCXaLz"
                    },
                    "Action" : [ "secretsmanager:DescribeSecret", "secretsmanager:Get*", "secretsmanager:List*" ],
                    "Resource" : "*"
                } ]
            }, # Required
            secret_id=mfl_odds_secret.attr_id # Required
        )

        CloudFrontToApiGatewayToLambda(
            self, 'CloudFrontApiGatewayToLambda',
            lambda_function_props=_lambda.FunctionProps(
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset('mfl_odds', 
                    exclude=['.envrc','games.json']
                ),
                handler='gather.lambda_handler',
                layers=[self.create_dependencies_layer('mfl_odds', 'gather')],
                environment={
                    'API_KEY_THE_ODDS': mfl_odds_secret.secret_string
                }
            ),
            # NOTE - we use RestApiProps here because the actual type, LambdaRestApiProps requires
            # the handler function which does not yet exist. As RestApiProps is a subset of of LambdaRestApiProps
            # (although does not *extend* that interface) this works fine when the props object reaches the 
            # underlying TypeScript code that implements Constructs
            api_gateway_props=apigw.RestApiProps(
                default_method_options=apigw.MethodOptions(
                    authorization_type=apigw.AuthorizationType.NONE
                )
            )
        )
        
        
    def create_dependencies_layer(self, project_name, function_name: str) -> _lambda.LayerVersion:
        requirements_file = "mfl_odds/requirements.txt"  # 👈🏽 point to requirements.txt
        output_dir = ".build/app"  # 👈🏽 a temporary directory to store the dependencies

        if not os.environ.get("SKIP_PIP"):
            # 👇🏽 download the dependencies and store them in the output_dir
            subprocess.check_call(f"pip install -r {requirements_file} -t {output_dir}/python".split())

        layer_id = f"{project_name}-{function_name}-dependencies"  # 👈🏽 a unique id for the layer
        layer_code = _lambda.Code.from_asset(output_dir)  # 👈🏽 import the dependencies / code

        my_layer = _lambda.LayerVersion(
            self,
            layer_id,
            code=layer_code,
        )

        return my_layer
    



        
