# DriveWise infrastructure (AWS CDK, Python)

One stack, `DriveWiseStack`, in us-west-2. Everything in it is billed per use,
so it costs close to nothing when idle.

## Phase 1: ingest path
```
upload CSV -> S3 RawBucket (raw/...) -> S3 event (raw/*.csv) -> IngestFn -> DynamoDB Table (+GSI1)
```

| Resource | Notes |
|----------|-------|
| `RawBucket` | Public access blocked, SSE-S3, TLS only. `raw/` moves to Infrequent Access after 30 days. **Retained** on `cdk destroy` (it is the source of truth). |
| `Table` | `PK`/`SK` + `GSI1`, on-demand billing (ADR 0003). Destroyed with the stack, because it can be rebuilt from S3. |
| `IngestFn` | Python 3.13, arm64, 512 MB, 60 s. Code is `lambdas/ingest/` plus `lambdas/ingest/requirements.txt`. |
| `IngestLogs` | 14-day retention (Lambda's default keeps logs forever). |
| IAM | Read `raw/*` only. DynamoDB `GetItem`, `PutItem` and `BatchWriteItem` only. |

Bundling runs `pip install` locally (no Docker, which CloudShell lacks) and
targets Linux arm64 wheels, so it gives the same result from Windows or
CloudShell.

## Deploy (CloudShell)
```bash
cd DriveWise && git pull
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk diff            # review what will change
cdk deploy
./smoke_test.sh     # upload the sample twice; expect 1 trip, then "duplicate"
```

## Test (no AWS needed)
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q     # assertions on the synthesized template
```

## Tear down
`cdk destroy` removes everything except `RawBucket`. Delete the bucket by
hand (empty it first) if you really want the raw data gone.
