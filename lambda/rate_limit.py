import boto3
import botocore
import time
import math
import random
import datetime
import json
import uuid
from botocore.config import Config

table_name = 'buckets_table'

class UsagePlan:
    """UsagePlan defines how RateLimit should throttle requests."""
    def __init__(self, rate_limit, burst_rate=0, granularity_in_sec=60):
        self.granularity_in_sec = granularity_in_sec
        self.max_rate = 500 * self.granularity_in_sec
        self.rate_limit = rate_limit
        self.burst_rate = burst_rate

        if rate_limit >= burst_rate:
            self.type = 'LeakyBucket'
            self.number_bucket_shards = int(math.ceil(rate_limit/self.max_rate))
        else:
            self.type = 'TokenBucket'
            #burst_rate needs to be at least 2*rate_limit.
            self.burst_rate = self.burst_rate if self.burst_rate > 2 * self.rate_limit else 2 * self.rate_limit
            self.number_bucket_shards = int(math.ceil(burst_rate/self.max_rate))

        self.base_tokens_per_shard = self.distribute(self.rate_limit, self.number_bucket_shards)
        self.burst_tokens_per_shard = self.distribute(self.burst_rate, self.number_bucket_shards)

    def distribute(self, tokens, bucket_shard_count):
        base, extra = divmod(tokens, bucket_shard_count)
        return [base + (i < extra) for i in range(bucket_shard_count)]

class RateLimit:
    """
    RateLimit implements Leaky Bucket and Token Bucket algorithms. The implementation is distributed 
    and backed by DynamoDB.
    """

    def __init__(self, log_metrics=False):

        """
        RateLimit tries to create its own DynamoDB table if its missing. Its mandator to have 
        'dynamodb:DescribeTable' permissions for the executing role, 'dynamodb:CreateTable' is 
        optional if the table is pre-provisioned.
        """

        self.dynamodb_resource = boto3.resource(
            'dynamodb', 
            'eu-west-1', 
            config=Config(retries={'max_attempts': 1})
        )
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
            raise  

    def should_throttle(self, bucket_id, usage_plan):
        """
        The bucket containing the tokens is sharded, for scaleability. First draw a random shard 
        id from which to pick tokens. Tokens are picked from bucket_shards at random and if the 
        shard is empty throttle True is returned. Since the buckets are drawn at random not round
        robin, some throttling can happen before the full bucket is depleted of tokens.
        """
        bucket_shard_ids = list(range(0, usage_plan.number_bucket_shards))
        random.shuffle(bucket_shard_ids)
        bucket_shard_id = bucket_shard_ids.pop()

        throttle_by_ddb = False
        throttle = True

        try:
            tokens_in_bucket_shard = self.get_token(bucket_id, bucket_shard_id, usage_plan)
            throttle = tokens_in_bucket_shard <= 0
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ThrottlingException':
                raise 
            else:
                throttle_by_ddb = True
                
        if self.log_metrics:
            self.log_throttle_metrics(
                bucket_id,  
                throttle=throttle, 
                throttle_by_ddb=throttle_by_ddb,
            )
        return throttle

    def get_token(self, bucket_id, bucket_shard_id, usage_plan):
        global token
        now = int(time.time() / usage_plan.granularity_in_sec)
        tokens_in_bucket_shard = 0
        
        try:
            token = self.buckets_table.get_item(
                Key={'bucket_id': bucket_id, 'bucket_shard_id': bucket_shard_id},
            )
            item = token.get('Item',{})
            tokens_in_bucket_shard = token.get('Item',{}).get('token_count', 0)
            
            rate_limit_per_shard = usage_plan.base_tokens_per_shard[bucket_shard_id]
            
            if usage_plan.type is 'TokenBucket':
                refil_cap_per_shard = usage_plan.burst_tokens_per_shard[bucket_shard_id] - rate_limit_per_shard
            else:
                refil_cap_per_shard = rate_limit_per_shard
            
            if now > item.get('last_updated', 0) and tokens_in_bucket_shard <= refil_cap_per_shard:
                #refil
                token = self.refil_tokens(bucket_id, bucket_shard_id, usage_plan, refil_cap_per_shard, now)
                tokens_in_bucket_shard = token.get('Attributes',{}).get('token_count', 0)
                
            elif item.get('token_count', 0) > 0:
                #subtract
                token = self.subtract_token(bucket_id, bucket_shard_id, usage_plan, now)
                tokens_in_bucket_shard = token.get('Attributes',{}).get('token_count', 0)
            
            
                
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise         
        return tokens_in_bucket_shard
        
    def refil_tokens(self, bucket_id, bucket_shard_id, usage_plan, refil_cap_per_shard, now):
        global token
        try:
            #Refill bucket
            rate_limit_per_shard = usage_plan.base_tokens_per_shard[bucket_shard_id]
            attributes = {
                    ':now': now,
                    ':rate_limit': rate_limit_per_shard,
                }
                
            if usage_plan.type is 'TokenBucket':
                attributes[':refil_cap'] =  refil_cap_per_shard 
                condition_expression = 'attribute_not_exists(bucket_id) OR ( :now > last_updated AND (token_count < :refil_cap ) )'
                update_expression = 'SET last_updated = :now ADD token_count :rate_limit'
            else:    
                condition_expression = ':now > last_updated OR attribute_not_exists(bucket_id)'
                update_expression = 'SET last_updated = :now, token_count = :rate_limit'
            
            token =  self.buckets_table.update_item(
                Key={'bucket_id': bucket_id, 'bucket_shard_id': bucket_shard_id},
                UpdateExpression=update_expression,
                ConditionExpression=condition_expression,
                ExpressionAttributeValues=attributes,
                ReturnValues='ALL_NEW'
            )
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise 
        return token
        
    def subtract_token(self, bucket_id, bucket_shard_id, usage_plan, now):
        global token
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

    def log_throttle_metrics(self, bucket_id, throttle=False, throttle_by_ddb=False):
        """
        Metrics are logged using CloudWatch EMF format.
        """
        throttle_by_ddb_count = (0, 1)[throttle_by_ddb]
        throttle_count = (0, 1)[throttle]
        
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
                    },{
                        'Namespace': 'AWSSAMPLES/RateLimmit',
                        'Dimensions': [['BucketId']],
                        'Metrics': [
                            {
                                'Name': 'ThrottleByDynamoDB',
                                'Unit': 'Count'
                            }
                        ],
                    }
                ],
                'Timestamp': int(datetime.datetime.now().timestamp()*1000)
            },
            'BucketId': bucket_id,
            'Throttle': throttle_count,
            'ThrottleByDynamoDB': throttle_by_ddb_count,
            'requestId': str(uuid.uuid4()),
        }))
