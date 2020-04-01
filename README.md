# Fine grained Rate Limit demo.

## Fine grained Rate Limit demo.

Its common that customers ask for how to implement fine grained throttling in AWS. API Gateway´s usage plans are designed to be on a tenant level rather then on a user/device/ip level. Also there are alot of scenarios when requests are not routed through an API Gateway. These scenarios also need to be able to implement throttling.

This demo shows how to implement a fine grained rate limit function in a distributed syste such as a Serverless application. This demo implements two rate limiting algorithms, leaky bucket and token bucket. For more info on these see https://en.wikipedia.org/wiki/Leaky_bucket https://en.wikipedia.org/wiki/Token_bucket.

In short leaky bucket gives a steady rate while token bucket allows burst.

## Use cases & Considerations

This implementation (or modification of it) could be used to build Rate Limiting for either Users/Devices/Sub Systems within a Tenant where the the API Gateway Usage Plan is used to Rate Limit the Tenant. API Gateway Usge Plans should always be used first to move the first level of protection outside the customer runtime and into the AWS service. Alternativly this implementation (or modification of it) could be used in sitations where there is no API Gateway, either because of protocol used like UDP or simply due to legacy implementation.

The definition of a Usage Plan is needed for the Rate Limit function. The management and distribution of Usage Plans is not covered in this example. Though in the case where a rate limit is applied to users within a tenant its recommended that Usage Plans arnt stored per user but rather per group of users. This ensures that the usage_plans can be cached and dont need to be loaded from a database every single time.

Example: In the case of the demo_handler lambda function it throttles each requesting IP to 10 RPM with a burst to 50RPM
```python
from rate_limit import RateLimit, UsagePlan
usage_plans = {'normal_user': UsagePlan(10, 50))
rate_limit = RateLimit(log_metrics=True)
def handler(event, context):
    if rate_limit.should_throttle(event['requestContext']['identity']['sourceIp'], usage_plans['normal_user']):
        return {
            'statusCode': 429,
            'body': 'You got throttled'
        }
    return {
        'statusCode': 200,
        'body': 'All ok'
    }
```


## About the implementation

A `UsagePlan` is required for the `RateLimit`. Its left ouside the scope of this example how these are maintained and managed. A solution could be to have them in DynamoDB or Parameter Store, depending on how many usage plans you have and how often you reload them. Its a good idea to cache the `UsagePlan` in the distributed runtime.

The `RateLimit` class which which has a `should_throttle(bucket_id, usage_plan)` function, `bucket_id` is the unique id by which the Rate Limit is tracked, `usage_plan` is how much capacity should be given to that `bucket_id`. 

In the DynamoDB table that backs this implementaiton each bucket is divided into shards. This is to reduce the risk of hot partitions on dynamodb and throttling of queries. The number of shards created is `rate_limit/MAX_RATE` where `MAX_RATE` should be low enough to not create hot partitions, tokens are distributed evenly across the shards. Currently DyanmoDB supports 1000 WCU and which should be about 500 requests per second in this implementation. So the default is `MAX_RATE=250*60  #RPM`. Throttling can still occour as the shards gets depleated of tokens, in that case `should_throttle(bucket_id, usage_plan)` will return `True`. This means that for usage plans with either rate_limit or burst_limit above 15000 RPM we might see early throttling. 

This should only be a concern if bucket_id´s are per Tenant, Fleet of Devices or System. For Users or Devices within a tenant this shouldnt be a concern.

`RateLimit` creates a DynamoDB table if its missing and hten does PutItem and UpdateItem operarations on that table so the following IAM permissions are required.
````
          - Action:
              - dynamodb:DescribeTable
              - dynamodb:CreateTable
              - dynamodb:PutItem
              - dynamodb:UpdateItem
            Effect: Allow
            Resource:
              Fn::Join:
                - ""
                - - "arn:"
                  - Ref: AWS::Partition
                  - ":dynamodb:"
                  - Ref: AWS::Region
                  - ":"
                  - Ref: AWS::AccountId
                  - ":table/buckets_table"
````


## License

This library is licensed under the MIT-0 License. See the LICENSE file.

