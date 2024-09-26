from aws_cdk import (
    aws_apigateway as apigw,
    aws_cloudfront as cloudfront,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as _lambda,
    aws_secretsmanager as asm,
    CfnOutput,
    Duration,
    Fn,
    Stack
)
from aws_solutions_constructs.aws_apigateway_lambda import ApiGatewayToLambda
from aws_solutions_constructs.aws_cloudfront_apigateway_lambda import CloudFrontToApiGatewayToLambda
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

        mfl_odds_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[Fn.sub("arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:MflOddsPosterStack-ApiGatewayToLambdaPatternLambda-*")]
            )
        )

        mfl_odds_kms_key = kms.CfnKey(
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

        mfl_odds_secret = asm.CfnSecret(
            self,
            "mflOdds-ApiKey",
            description="api key for the-odds-api",
            kms_key_id=mfl_odds_kms_key.attr_key_id,
            name="mflOdds-ApiKey",
            # secret_string='l12345bno1'  # placeholder - manually replace with real secret after deploy
        )

        mfl_odds_secret_resource_policy = asm.CfnResourcePolicy(
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

        AgwToLmb = ApiGatewayToLambda(
            self,
            'ApiGatewayToLambdaPattern',
            lambda_function_props=_lambda.FunctionProps(
                # TODO: Add description
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset('lambda/post_odds'),
                handler='post.lambda_handler',
                layers=[self.create_dependencies_layer('lambda/post_odds', 'post')],
                role=mfl_odds_lambda_role,
                timeout=Duration.seconds(8),
                environment={
                    'SECRET_ARN': mfl_odds_secret.attr_id
                }
            )
        )

        cfnToAgwToLmb = CloudFrontToApiGatewayToLambda(
            self,
            'CloudFrontApiGatewayToLambda',
            lambda_function_props=_lambda.FunctionProps(
                # TODO: Add description
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset(
                    'lambda/gather_odds',
                    exclude=['.envrc', 'games.json']
                ),
                handler='gather.lambda_handler',
                layers=[self.create_dependencies_layer('lambda/gather_odds', 'gather')],
                role=mfl_odds_lambda_role,
                timeout=Duration.seconds(8),
                environment={
                    'SECRET_ARN': mfl_odds_secret.attr_id,
                    'POSTER_LAMBDA_ARN': AgwToLmb.lambda_function.function_arn
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
            ),
            # TODO: Set cache_policy on cloudfront distro to CacheDisabled = 4135ea2d-6df8-44a3-9df3-4b5a84be39ad
            # cloud_front_distribution_props=cloudfront.CfnDistributionProps(
            #     distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
            #         enabled=True,
            #         default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
            #             target_origin_id="targetOriginId",
            #             viewer_protocol_policy="viewerProtocolPolicy",
            #             cache_policy_id=cloudfront.CachePolicy.CACHING_DISABLED
            #         )
            #     )
            # )
        )

        CfnOutput(self, 'CloudFrontDistributionDomainName',
            value=cfnToAgwToLmb.cloud_front_web_distribution.domain_name
        )

        rule = events.Rule(
            self,
            "MyRule",
            schedule=events.Schedule.cron(
                # minute="59", hour="4", month="*", week_day="5", year="*")
                minute="0", hour="1", month="*", week_day="5", year="*")
                # 01:00 every Thursday UTC == 18:00 every Wednesday PT
        )

        # Set the Lambda function as the target of the rule
        rule.add_target(targets.LambdaFunction(cfnToAgwToLmb.lambda_function))

        events.RuleTargetConfig(
            arn=cfnToAgwToLmb.lambda_function.function_arn,
            role=mfl_odds_lambda_role
        )

    def create_dependencies_layer(
        self,
        project_name,
        function_name: str) -> _lambda.LayerVersion:
        requirements_file = "lambda/gather_odds/requirements.txt"  # 👈🏽 point to requirements.txt
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
