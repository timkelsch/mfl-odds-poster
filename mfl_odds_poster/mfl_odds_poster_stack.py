from aws_cdk import (
    aws_apigateway as apigw,
    aws_cloudfront as cloudfront,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_secretsmanager as asm,
    BundlingOptions,
    CfnOutput,
    Duration,
    Fn,
    Stack
)
from aws_solutions_constructs.aws_apigateway_lambda import ApiGatewayToLambda
from aws_solutions_constructs.aws_cloudfront_apigateway_lambda import CloudFrontToApiGatewayToLambda
from constructs import Construct


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

        mfl_odds_secret = asm.CfnSecret(
            self,
            "mflOdds-ApiKey",
            description="api key for the-odds-api",
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
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset(
                    'lambda/post_odds',
                    bundling=BundlingOptions(
                        image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                        command=[
                            'bash', '-c',
                            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
                        ],
                    ),
                ),
                handler='post.lambda_handler',
                role=mfl_odds_lambda_role,
                # login + host lookup + season API + post, each with retries
                timeout=Duration.seconds(30),
                environment={
                    'SECRET_ARN': mfl_odds_secret.attr_id
                }
            )
        )

        cfnToAgwToLmb = CloudFrontToApiGatewayToLambda(
            self,
            'CloudFrontApiGatewayToLambda',
            lambda_function_props=_lambda.FunctionProps(
                runtime=_lambda.Runtime.PYTHON_3_11,
                code=_lambda.Code.from_asset(
                    'lambda/gather_odds',
                    exclude=['.envrc', 'games.json'],
                    bundling=BundlingOptions(
                        image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                        command=[
                            'bash', '-c',
                            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
                        ],
                    ),
                ),
                handler='gather.lambda_handler',
                role=mfl_odds_lambda_role,
                # invokes the poster synchronously, so must exceed its timeout;
                # 2026-05-14 run hit 7.9s of the old 8s limit
                timeout=Duration.seconds(60),
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
                minute="0", hour="22", month="*", week_day="4", year="*")
                # 22:00 every Wednesday UTC == 15:00 PT / 16:00 MT Wednesday.
                # Must precede Wednesday/Thursday kickoffs (2026 opener was a
                # Wednesday 17:20 PT); the old 01:00 Thursday UTC fired after.
        )

        # Set the Lambda function as the target of the rule
        rule.add_target(targets.LambdaFunction(cfnToAgwToLmb.lambda_function))

        events.RuleTargetConfig(
            arn=cfnToAgwToLmb.lambda_function.function_arn,
            role=mfl_odds_lambda_role
        )

