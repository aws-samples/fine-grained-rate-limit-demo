import boto3
import botocore
import time
import math
import random
import datetime
import json

table_name = 'buckets_table'
leaky_buket_condition_expression = ':now > last_updated OR attribute_not_exists(bucket_id) AND :rate_limit > :burst_rate'
leaky_buket_update_expression = 'SET token_count = :rate_limit'
token_buket_condition_expression = 'attribute_not_exists(bucket_id) OR ( :now > last_updated AND attribute_exists(token_count) AND token_count < :burst_rate )'
token_update_expression = 'ADD token_count  :rate_limit'
MAX_RATE=250*60

class UsagePlan:
    def __init__(self, rate_limit, burst_rate=0):
        self.rate_limit = rate_limit
        self.burst_rate = burst_rate

        if rate_limit >= burst_rate:
            self.type = 'LeakyBucket'
            self.condition_expression = leaky_buket_condition_expression
            self.update_expression = leaky_buket_update_expression
            self.number_bucket_shards = int(math.ceil(rate_limit/MAX_RATE))
        else:
            self.type = 'TokenBucket'
            self.condition_expression = token_buket_condition_expression
            self.update_expression = token_update_expression
            self.number_bucket_shards = int(math.ceil(burst_rate/MAX_RATE))

        self.base_tokens_per_shard = self.distribute(self.rate_limit, self.number_bucket_shards)
        self.burst_tokens_per_shard = self.distribute(self.burst_rate, self.number_bucket_shards)

    def distribute(self, tokens, bucket_shard_count):
        base, extra = divmod(tokens, bucket_shard_count)
        return [base + (i < extra) for i in range(bucket_shard_count)]

class RateLimit:

    def __init__(self, log_metrics=False):
        self.dynamodb_resource = boto3.resource('dynamodb', 'eu-west-1')
        dynamodb_client = boto3.client('dynamodb')

        try:
            dynamodb_client.describe_table(TableName=table_name)
        except dynamodb_client.exceptions.ResourceNotFoundException:
            self.create_table()
            pass

        self.buckets_table = self.dynamodb_resource.Table(table_name)
        self.buckets_table.wait_until_exists()
        self.log_metrics = log_metrics

    def create_table(self):
        try:
            self.dynamodb_resource.create_table(    
                TableName=table_name,
                KeySchema=[
                    {
                        'AttributeName': 'bucket_id',
                        'KeyType': 'HASH'
                    },{
                        'AttributeName': 'bucket_shard_id',
                        'KeyType': 'RANGE'
                    },
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'bucket_id',
                        'AttributeType': 'S'
                    },{
                        'AttributeName': 'bucket_shard_id',
                        'AttributeType': 'N'
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
        except botocore.exceptions.ClientError as e:
            print(e.response['Error']['Code'])
            raise  
                              

    def should_throttle(self, bucket_id, usage_plan):
        bucket_shard_ids = list(range(0, usage_plan.number_bucket_shards))
        random.shuffle(bucket_shard_ids)

        try:
            while len(bucket_shard_ids):
                bucket_shard_id = bucket_shard_ids.pop()
                token = self.get_token(bucket_id, bucket_shard_id, usage_plan)

                if token.get('Attributes',{}).get('token_count',0) > 0:
                    return False

        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ThrottlingException':
                raise 
        
        if self.log_metrics:
            self.log_throttle_metrics(bucket_id)

        return True

    def get_token(self, bucket_id, bucket_shard_id, usage_plan):
        now = int(time.time() / 60)
        token = {}
        try:
            #Refill bucket
            self.buckets_table.update_item(
                Key={'bucket_id': bucket_id, 'bucket_shard_id': bucket_shard_id},
                UpdateExpression=usage_plan.update_expression,
                ConditionExpression=usage_plan.condition_expression,
                ExpressionAttributeValues={
                    ':now': now,
                    ':rate_limit': usage_plan.base_tokens_per_shard[bucket_shard_id],
                    ':burst_rate': usage_plan.burst_tokens_per_shard[bucket_shard_id],
                },
                ReturnValues='ALL_NEW'
            )
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise 
        try:
            token =  self.buckets_table.update_item(
                Key={'bucket_id': bucket_id, 'bucket_shard_id': bucket_shard_id},
                ExpressionAttributeValues={':mod': -1, ':now': now, ':min_val': 0},
                UpdateExpression='SET last_updated = :now ADD token_count :mod',
                ConditionExpression='token_count > :min_val',
                ReturnValues='ALL_NEW'
            )           
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise  
        return token

    def log_throttle_metrics(self, bucket_id):
        print(json.dumps({
            '_aws': {
                'CloudWatchMetrics': [
                    {
                        'Namespace': 'AWSSAMPLES/RateLimmit',
                        'Dimensions': [['BucketId']],
                        'Metrics': [
                            {
                                'Name': 'Throttle',
                                'Unit': 'Count'
                            }
                        ],
                    }
                ],
                'Timestamp': int(datetime.datetime.now().timestamp()*1000)
            },
            'BucketId': bucket_id,
            'Throttle': 1,
        }))