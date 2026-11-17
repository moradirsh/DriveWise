"""DriveWise Phase 1: S3 raw bucket -> ingest Lambda -> DynamoDB.

See docs/decisions/0001 (S3 + DynamoDB) and 0003 (key design).
Everything here is pay-per-use; nothing bills by the hour while idle.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import jsii
from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    DockerImage,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_SRC = REPO_ROOT / "lambdas" / "ingest"

LAMBDA_PYTHON = "3.13"
RAW_PREFIX = "raw/"


@jsii.implements(ILocalBundling)
class _LocalPipBundler:
    """Bundle a Python Lambda without Docker (CloudShell has no Docker).

    Copies the source .py files and pip-installs requirements.txt as
    Linux/arm64 wheels for the Lambda's Python version, so the result matches
    the runtime even when built on Windows or a different Python.
    """

    def __init__(self, src: Path):
        self.src = src

    def try_bundle(self, output_dir: str, *_options, **_kw) -> bool:
        # jsii passes the BundlingOptions struct positionally; we don't need it.
        out = Path(output_dir)
        for f in self.src.glob("*.py"):
            shutil.copy2(f, out / f.name)
        req = self.src / "requirements.txt"
        if req.exists():
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "-r", str(req), "-t", str(out),
                 "--platform", "manylinux2014_aarch64",
                 "--python-version", LAMBDA_PYTHON,
                 "--implementation", "cp",
                 "--only-binary=:all:"],
                check=True,
            )
        return True


class InfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Raw uploads. The source of truth: DynamoDB can be rebuilt from it,
        # so it survives `cdk destroy` (RETAIN).
        raw_bucket = s3.Bucket(
            self, "RawBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="raw-to-infrequent-access",
                    prefix=RAW_PREFIX,
                    transitions=[s3.Transition(
                        storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                        transition_after=Duration.days(30),
                    )],
                ),
                s3.LifecycleRule(
                    id="abort-incomplete-uploads",
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
        )

        # Single table, ADR 0003. Derived data (replayable from S3), so it is
        # destroyed with the stack and has no point-in-time recovery.
        table = dynamodb.Table(
            self, "Table",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(name="GSI1PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="GSI1SK", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # Explicit log group: the Lambda default keeps logs forever.
        ingest_logs = logs.LogGroup(
            self, "IngestLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        ingest_fn = lambda_.Function(
            self, "IngestFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,  # cheaper per GB-second
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                str(INGEST_SRC),
                exclude=["__pycache__", "*.pyc"],
                bundling=BundlingOptions(
                    image=DockerImage.from_registry("unused-local-bundling-only"),
                    local=_LocalPipBundler(INGEST_SRC),
                ),
            ),
            memory_size=512,
            timeout=Duration.seconds(60),
            environment={"TABLE_NAME": table.table_name},
            log_group=ingest_logs,
        )

        # Least privilege: read only raw/ objects; only the three DynamoDB
        # calls handler.py makes (no Scan, Delete, Query, or table admin).
        raw_bucket.grant_read(ingest_fn, f"{RAW_PREFIX}*")
        table.grant(ingest_fn, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchWriteItem")

        raw_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(ingest_fn),
            s3.NotificationKeyFilter(prefix=RAW_PREFIX, suffix=".csv"),
        )

        CfnOutput(self, "RawBucketName", value=raw_bucket.bucket_name)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "IngestFunctionName", value=ingest_fn.function_name)
        CfnOutput(self, "IngestLogGroupName", value=ingest_logs.log_group_name)
