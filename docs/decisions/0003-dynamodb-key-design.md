# 0003: DynamoDB single-table key design

Status: accepted

## Context
DynamoDB holds only per-trip summaries (ADR 0001); raw CSVs stay in S3.
The data is small: one car, a few trips a day, about 25 parameters per trip.
With DynamoDB you design the keys around the queries you need, so these are
the queries the pipeline has to answer:

| # | Access pattern | Used by |
|---|----------------|---------|
| 1 | Latest N trips for a vehicle, newest first | dashboard, report |
| 2 | All parameter summaries for one trip | report |
| 3 | One parameter's history across trips, by time | baseline, drift detection |
| 4 | Current baseline for one parameter of a vehicle | detection |
| 5 | "Has this exact file already been ingested?" | ingest (idempotency) |

## Decision
One table with on-demand billing, generic `PK`/`SK` keys and one global
secondary index (GSI1).

| Item | PK | SK | GSI1PK | GSI1SK |
|------|----|----|--------|--------|
| Trip | `VEH#<id>` | `TRIP#<start_iso>#<trip_id>` | - | - |
| Summary | `VEH#<id>` | `SUM#<trip_id>#<param>` | `VEH#<id>#PARAM#<param>` | `<start_iso>` |
| Baseline | `VEH#<id>` | `BASE#<param>` | - | - |

- `start_iso` is the trip's first reading in UTC (`2026-11-07T22:53:58Z`).
  ISO 8601 sorts correctly as a plain string.
- `trip_id` is the first 16 hex characters of the raw file's SHA-256.

How each access pattern is served:
1. `Query PK=VEH#<id>, SK begins_with "TRIP#"`, `ScanIndexForward=false`, `Limit=N`.
   Time sorting comes for free because `start_iso` comes before `trip_id` in the SK.
2. `Query PK=VEH#<id>, SK begins_with "SUM#<trip_id>#"`.
3. `Query GSI1 GSI1PK=VEH#<id>#PARAM#<param>`, optionally with
   `GSI1SK BETWEEN <from> AND <to>`. This is the query that baselines and drift
   detection depend on.
4. `GetItem PK=VEH#<id>, SK=BASE#<param>`.
5. `GetItem` on the trip key, plus a conditional put (see Idempotency below).

### Why a single table
Every pattern is scoped to one vehicle, so everything for a car lives in one
partition, and most reads are a single `Query`. Separate Trips, Summaries and
Baselines tables would mean three tables to provision, grant and back up, with
nothing gained: DynamoDB has no joins, so splitting the data would not make any
query easier.

### Why on-demand billing
The project rule is near-zero cost when idle. On-demand charges per request
and nothing when the table is idle. Provisioned capacity charges every hour,
even at low settings. At this volume (hundreds of writes a day at most),
on-demand is effectively free.

### Why only summary items are in GSI1
GSI1 exists for pattern 3. Trip and baseline items leave out the GSI1
attributes, so DynamoDB does not copy them into the index. That avoids paying
index write and storage costs for items the index is never used for (a
"sparse index").

### Idempotency and the commit marker
S3 event notifications are at-least-once, and a re-upload of the same file
should not create a second trip. The ingest handler:
1. Computes `trip_id` from the file bytes. The same file always gives the same keys.
2. Skips early if the trip item already exists. This read is cheap but not
   race-safe.
3. Writes all summary items. They have deterministic keys, so a retry
   overwrites them with identical data.
4. Writes the trip item last, with `ConditionExpression=attribute_not_exists(PK)`.

The trip item is the commit marker: a trip "exists" only once that item is
written. If the Lambda crashes in step 3, there is no trip item, and the retry
redoes steps 3-4. If two identical uploads run at the same time, both pass step
2, both write identical summaries (harmless), and exactly one wins the
conditional put. The other gets `ConditionalCheckFailed` and reports `duplicate`.

## Tradeoffs
- **Uncommitted summaries are visible through GSI1.** If ingest fails after
  writing some summaries and never succeeds on retry (for example, it ends up
  in a dead-letter queue), those summaries have no trip item but still appear
  in pattern 3. Baseline and detect code must only use summaries whose
  `trip_id` has a trip item, for example by loading the vehicle's trip IDs
  (pattern 1) and filtering.
  Alternative considered: a DynamoDB transaction for all items. It was rejected
  because a transaction is capped at 100 items, costs twice as much per write,
  and the problem is easy to filter for.
- **Idempotency is per exact file.** Re-exporting the same drive with any
  byte difference produces a new `trip_id` and a second trip. That's acceptable
  for one manual uploader.
- **No queries across vehicles.** "All cars with high fuel trims" would need a
  scan or a new index. Not needed for a single-owner tool.
- **Hot partition risk is negligible.** One vehicle writes a few trips a day,
  far below the per-partition limits (1,000 writes/s). The table has no local
  secondary index, so there is no 10 GB per-vehicle size limit.
- **Item size is small.** A summary item holds three windows of five
  statistics, far below DynamoDB's 400 KB item limit.
- **GSI1 is eventually consistent.** A baseline computed right after ingest
  might miss the newest trip for a moment. That doesn't matter at
  trend-over-weeks timescales.

## Open questions
- Baseline items (`BASE#<param>`) are not written yet. Their attributes
  (median, MAD, number of trips, computed_at) get decided with the baseline
  Lambda.
- Should failed ingests also clean up their partial summaries? This depends on
  the SQS + DLQ design (roadmap step 3).
