# 0001: Raw data in S3, per-second aggregates in DynamoDB

Status: proposed

## Context
The A30M records about 10 samples per second. A 30-minute drive with 10
parameters would be around 180k raw readings. Drift detection works on trends
over weeks, so it does not need 10 Hz resolution.

## Decision
- Store the original uploaded CSV in S3 (cheap, replayable, nothing lost).
- On ingest, collapse readings into per-second min/max/mean/count per
  parameter and write only those to DynamoDB.

## Evidence so far
On the first sample file (8 parameters, ~19 seconds): 1,450 raw readings
became 157 per-second aggregates, about a 9x reduction.

## Tradeoffs
- Sub-second events (a brief stumble) are only visible in the S3 raw file,
  not in DynamoDB. Acceptable because detection targets slow drift.
- Raw files in S3 let me re-aggregate later if I change the window size.

## Open questions
- Is 1 second the right bucket, or should aggregates be per 5-10 seconds?
- DynamoDB key design (partition by vehicle, sort by parameter and time)
  still needs an access-pattern review.

## Update (Car Scanner data)
Car Scanner delivers about 0.35-0.7 readings per second per sensor, not 10 Hz,
so a 1-second bucket is mostly empty. Use 10-second buckets (or per-trip
summaries) for this source. On a 4.4-minute sample, 4,545 allowlisted readings
became 680 ten-second buckets.
