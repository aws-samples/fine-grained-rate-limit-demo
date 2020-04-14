from aws_cdk import (
    core as _core,
    aws_apigateway as _apigateway,
    aws_lambda as _lambda,
    aws_iam as _iam,
)


class AppStack(_core.Stack):

    def __init__(self, scope: _core.Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        code = _lambda.Code.asset('lambda/.dist/lambda.zip')
        function = _lambda.Function(self,
                                        'rate-limit-demo',
                                        function_name='rate-limit-demo',
                                        runtime=_lambda.Runtime.PYTHON_3_6,
                                        code=code,
                                        handler='demo_handler.handler',
                                        tracing=_lambda.Tracing.ACTIVE,
                                        )
        bucket_tokens_table = _core.Stack.format_arn(self,
                                                service='dynamodb',
                                                resource='table',
                                                sep='/',
                                                resource_name='buckets_table')
        rate_limit_ddb_statement = _iam.PolicyStatement()
        rate_limit_ddb_statement.add_resources(bucket_tokens_table)
        rate_limit_ddb_statement.add_actions('dynamodb:DescribeTable')
        rate_limit_ddb_statement.add_actions('dynamodb:CreateTable')
        rate_limit_ddb_statement.add_actions('dynamodb:GetItem')
        rate_limit_ddb_statement.add_actions('dynamodb:PutItem')
        rate_limit_ddb_statement.add_actions('dynamodb:UpdateItem')

        function.add_to_role_policy(rate_limit_ddb_statement)
        api = _apigateway.LambdaRestApi(self,'rate-limit-demo-api', handler=function)
