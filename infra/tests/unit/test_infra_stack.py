"""Assertions on the synthesized CloudFormation template (no AWS calls).

Run from infra/: python -m pytest -q
Bundling is skipped here (aws:cdk:bundling-stacks = []), so tests don't pip install.
"""
import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.infra_stack import InfraStack


@pytest.fixture(scope="module")
def template():
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    stack = InfraStack(app, "TestStack", env=cdk.Environment(account="123456789012", region="us-west-2"))
    return Template.from_stack(stack)


def test_bucket_blocks_public_access_and_is_encrypted(template):
    template.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
    })


def test_bucket_denies_non_tls_requests(template):
    template.has_resource_properties("AWS::S3::BucketPolicy", {
        "PolicyDocument": {"Statement": Match.array_with([Match.object_like({
            "Effect": "Deny",
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        })])},
    })


def test_raw_bucket_survives_stack_deletion(template):
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain"})


def test_raw_prefix_moves_to_infrequent_access(template):
    template.has_resource_properties("AWS::S3::Bucket", {
        "LifecycleConfiguration": {"Rules": Match.array_with([Match.object_like({
            "Prefix": "raw/", "Status": "Enabled",
            "Transitions": [{"StorageClass": "STANDARD_IA", "TransitionInDays": 30}],
        })])},
    })


def test_table_matches_adr_0003(template):
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                      {"AttributeName": "SK", "KeyType": "RANGE"}],
        "GlobalSecondaryIndexes": [{
            "IndexName": "GSI1",
            "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"},
                          {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
    })


def test_no_hourly_billed_resources(template):
    # Cost rule: nothing that charges per hour while idle.
    for rtype in ["AWS::EC2::NatGateway", "AWS::ElastiCache::CacheCluster",
                  "AWS::RDS::DBInstance", "AWS::EC2::Instance"]:
        template.resource_count_is(rtype, 0)


def test_ingest_lambda_config(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "handler.handler",
        "Runtime": "python3.13",
        "Architectures": ["arm64"],
        "MemorySize": 512,
        "Timeout": 60,
        "Environment": {"Variables": {"TABLE_NAME": Match.any_value()}},
    })


def test_logs_expire(template):
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 14})


def test_s3_triggers_lambda_only_for_raw_csv(template):
    template.has_resource_properties("Custom::S3BucketNotifications", {
        "NotificationConfiguration": {"LambdaFunctionConfigurations": [Match.object_like({
            "Events": ["s3:ObjectCreated:*"],
        })]},
    })
    config = list(template.find_resources("Custom::S3BucketNotifications").values())[0]
    rules = config["Properties"]["NotificationConfiguration"]["LambdaFunctionConfigurations"][0]["Filter"]["Key"]["FilterRules"]
    assert {(r["Name"], r["Value"]) for r in rules} == {("prefix", "raw/"), ("suffix", ".csv")}


def _ingest_policy_statements(template):
    policies = template.find_resources("AWS::IAM::Policy")
    ingest = [p for name, p in policies.items() if name.startswith("IngestFn")]
    assert len(ingest) == 1, list(policies)
    return ingest[0]["Properties"]["PolicyDocument"]["Statement"]


def test_ingest_dynamodb_access_is_least_privilege(template):
    ddb_actions = set()
    for st in _ingest_policy_statements(template):
        actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        assert "*" not in actions and "dynamodb:*" not in actions
        ddb_actions |= {a for a in actions if a.startswith("dynamodb:")}
    assert ddb_actions == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchWriteItem"}


def test_ingest_cannot_write_to_s3(template):
    for st in _ingest_policy_statements(template):
        actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        assert not any(a.startswith("s3:Put") or a.startswith("s3:Delete") for a in actions)


def test_ingest_s3_read_is_scoped_to_raw_prefix(template):
    s3_statements = [st for st in _ingest_policy_statements(template)
                     if any(a.startswith("s3:") for a in
                            (st["Action"] if isinstance(st["Action"], list) else [st["Action"]]))]
    assert s3_statements
    flat = str([st["Resource"] for st in s3_statements])
    assert "/raw/*" in flat
