# DriveWise

Serverless AWS pipeline that ingests OBD-II telemetry from any gasoline vehicle,
learns each car's own baseline, detects drift over time, and generates
plain English health reports.

> Status: early development. Parsing, unit normalization, per-trip summaries and the
> idempotent ingest handler work locally (tested against fake S3 and DynamoDB). AWS
> infrastructure, baselines, detection, and reports are not built yet.

## Why I built this
Scanner apps show live gauges and trouble codes. They don't track long-term
trends or explain what changed. DriveWise focuses on predictive maintenance
for an aging daily driver: catching slow drift (fuel trims, coolant temps,
battery voltage) before it becomes a repair.

## Planned pipeline
ingest -> store -> baseline -> detect -> report -> dashboard

- **Ingest:** per-source adapters turn each app's export into one generic shape
- **Store:** raw files in S3, per-second aggregates in DynamoDB keyed by `vehicle_id`
- **Analyze:** per-vehicle baselines, then drift detection with rules and statistics
- **Report:** detected findings sent to Claude for a plain-English explanation
- **Observe:** CloudWatch metrics, alarms, and dashboard

## Data sources
| Source | Format | Status |
|--------|--------|--------|
| XTool AnyScan A30M | CSV, epoch-ms timestamps, `Name--unit` headers | Parser done |
| ELM327 BLE dongle + Car Scanner | CSV, `SECONDS;PID;VALUE;UNITS` | Parser done |

## Scope
Works with OBD-II gasoline vehicles that expose standard (SAE J1979) PIDs.
Manufacturer-specific parameters are stored when present but not required.
EVs and most hybrids are out of scope.

## Run the tests
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest -q
```

## Repo layout
- `lambdas/ingest/`: source adapters and aggregation (working)
- `lambdas/baseline|detect|report/`: not started
- `infra/`: IaC, not started
- `sample-data/`: real recordings (no VIN or GPS); see `.gitignore` rules
- `docs/decisions/`: short notes on why each design choice was made

## Design decisions
- [0001: raw data in S3, aggregates in DynamoDB](docs/decisions/0001-raw-in-s3-aggregates-in-dynamodb.md)
- [0002: sensor allowlist and canonical units at ingest](docs/decisions/0002-allowlist-and-canonical-units.md)
- [0003: DynamoDB single-table key design](docs/decisions/0003-dynamodb-key-design.md)

## What I learned
(Filled in as I build.)
