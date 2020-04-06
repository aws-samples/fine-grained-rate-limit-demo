from rate_limit import RateLimit, UsagePlan

usage_plan = UsagePlan(1500, 2000)
rate_limit = RateLimit(log_metrics=True)

def handler(event, context):
    if rate_limit.should_throttle(event['requestContext']['identity']['sourceIp'], usage_plan):
        return {
            'statusCode': 429,
            'body': 'You got throttled'
        }
    return {
        'statusCode': 200,
        'body': 'All ok'
    }
