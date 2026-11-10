#!/usr/bin/env python3
import os
import aws_cdk as cdk
from infra.infra_stack import InfraStack

app = cdk.App()
InfraStack(app, "DriveWiseStack",
    env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"),
                        region="us-west-2"))
cdk.Tags.of(app).add("project", "drivewise")
app.synth()
