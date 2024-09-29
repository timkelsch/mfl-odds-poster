import aws_cdk as core
import aws_cdk.assertions as assertions

from mfl_odds_poster.mfl_odds_poster_stack import MflOddsPosterStack

# example tests. To run these tests, uncomment this file along with the example
# resource in mfl_odds_poster/mfl_odds_poster_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = MflOddsPosterStack(app, "mfl-odds-poster")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
