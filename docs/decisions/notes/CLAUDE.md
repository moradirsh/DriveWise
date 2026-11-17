# DriveWise

Serverless AWS pipeline (us-west-2, CDK in Python) that ingests OBD-II telemetry
from any OBD-II gasoline car (owner's car: 2016 Mazda 6), builds per-vehicle
baselines, detects slow drift (fuel trims, coolant, battery), and generates
plain-English health reports with Claude on Bedrock. Portfolio project for
cloud/AI internships: everything must be explainable and defensible in an interview.

## Working style
- The owner wants honest criticism and pushback. Say when an idea is weak and propose a better path.
- Rules detect, AI explains. The detection logic (baselines, drift) is written by the owner so they can defend it; guide, don't write it for them.
- Keep AWS cost near zero when idle: no NAT gateways, ElastiCache or other hourly-billed resources. Budget alarm is $10/month.
- Repo is public: never commit VINs, secrets, keys or private drive logs. Big private drives stay local.

## Architecture (target)
phone export -> presigned S3 upload -> (later SQS + DLQ) -> ingest Lambda -> DynamoDB
-> baseline/detect Lambdas -> report Lambda (Bedrock) -> SNS email; CloudWatch dashboard/alarms.
Caching belongs on a future read API. Athena was deliberately skipped.

- S3 raw keys (Hive-style): `raw/vehicle_id=<id>/date=YYYY-MM-DD/trip.csv`. Raw CSV is never modified.
- DynamoDB, single table, on-demand. `PK=VEH#<id>`; `SK` = `TRIP#<start_iso>#<trip_id>`,
  `SUM#<trip_id>#<param>`, `BASE#<param>`. GSI1: `GSI1PK=VEH#<id>#PARAM#<param>`, `GSI1SK=<start_iso>`.
  (Key design still to be written up as docs/decisions/0003.)
- Aggregates only in DynamoDB: per-trip, per-parameter summaries split by condition
  (`all`, `warm_idle`, `warm_cruise`). Fuel trims only mean something warm (coolant >= 80 C)
  at idle or steady cruise. Baselines need about 5 trips; before that say "not enough data yet".
- Idempotency: `trip_id = sha256(file)[:16]`. Write SUM items first, TRIP item last with
  `attribute_not_exists(PK)` as the commit marker.
- Timestream for LiveAnalytics is closed to new customers, hence DynamoDB + S3.

## Data sources
- Car Scanner ELM OBD2 (iPhone) + Vgate iCar Pro BLE dongle: CSV `"SECONDS";"PID";"VALUE";"UNITS";`
  semicolon-delimited and quoted, seconds since local midnight, date comes from the filename
  `YYYY-MM-DD_HH-MM-SS.csv` (the app sometimes writes a space instead of `_`; both are accepted). Degrees F are written as U+2109. "Equivalence ratio" is really AFR
  (divide by 14.7 for lambda). It records every listed sensor plus app extras, so the parser
  filters with an ALLOWLIST and converts to canonical units. Roughly 0.35-0.7 Hz per sensor.
- XTOOL A30M (AnyScan): CSV with epoch-ms first column, `Name--unit` headers, 8-parameter cap.
  Parser exists (`parse_a30m.py`) but the ingest handler does not accept it yet.

## Layout
- `lambdas/ingest/`: `parse_car_scanner.py`, `parse_a30m.py`, `aggregate.py`, `trip_summary.py`, `handler.py`
- `infra/`: CDK app (`app.py`, `infra/infra_stack.py`); pins us-west-2, tags `project=drivewise`
- `docs/decisions/`: ADRs (0001 raw in S3 and aggregates in DynamoDB, 0002 allowlist and canonical units)
- `sample-data/`: public-safe samples only. `.gitignore` ignores `sample-data/*.csv` except explicitly
  un-ignored small samples; full drives live in `sample-data/private/` (ignored).
- Tests: from the repo root, `.venv\Scripts\python -m pytest -q` (`pytest.ini` sets `testpaths = tests`).
  No AWS needed. Tests read `sample-data/2026-11-07_14-53-58.csv`. `tzdata` is required on Windows
  (no system tz database) and must also be packaged with any Lambda that uses `zoneinfo`.

## Deploying
Deploys run from AWS CloudShell (Node 22, `cdk deploy`); `cdk destroy` when done experimenting.
CloudShell home is about 1 GB, so install Node with `nvm install 22 -b` (binary only).

## Status
Done: repo, parsers, aggregation, CDK scaffold deployed, ingest handler and trip summaries
(tested locally with fake S3 and DynamoDB).
Next (roadmap revised 2026-11-14):
0. (done 2026-11-16) Housekeeping: handler/trip_summary committed, ADR 0001 accepted, README updated.
1. (done 2026-11-16) ADR 0003 written. Consequence for step 4: baseline/detect must ignore SUM items
   whose trip_id has no TRIP item (uncommitted ingests are visible through GSI1).
2. Phase 1 CDK stack: S3 bucket (public access blocked, lifecycle), DynamoDB table + GSI1,
   Python ingest Lambda (bundle `tzdata`), S3 notification on `raw/` for `.csv`, least-privilege
   grants, Lambda log retention set (default is never-expire). Deploy and test with the sample CSV,
   then upload it twice to prove duplicates are skipped; script that test for the README.
3. SQS + DLQ between S3 and ingest (moved up from step 5): a malformed CSV or the ADR 0002
   unit-mismatch error must land somewhere visible, not fail silently.
4. Baseline/detect Lambdas (median/MAD, at least 5 trips, slope for drift), tested on synthetic
   drift data. First check on the real drives in `sample-data/private/` how many samples per trip
   survive the `warm_idle`/`warm_cruise` filters at 0.35-0.7 Hz.
5. Bedrock report Lambda + EventBridge + SNS; upload API; read API with caching.
6. CloudWatch dashboard/alarms; load and failure tests; fill in README (cost, results, lessons).
7. A30M ingest mapping.
