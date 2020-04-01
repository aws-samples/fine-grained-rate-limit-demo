#!/usr/bin/env python3
import os
from aws_cdk import core
from app_stack import AppStack

app = core.App()
AppStack(app, 'rate-limit-demo', env=core.Environment(
    account=os.environ.get("CDK_DEPLOY_ACCOUNT", os.environ["CDK_DEFAULT_ACCOUNT"]),
    region=os.environ.get("CDK_DEPLOY_REGION", os.environ["CDK_DEFAULT_REGION"])))
app.synth()
