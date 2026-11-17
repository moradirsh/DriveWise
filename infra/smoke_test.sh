#!/usr/bin/env bash
# Phase 1 end-to-end check against the deployed stack (run in CloudShell from infra/).
#   1. upload a sample CSV to raw/ -> expect 1 TRIP item + SUM items in DynamoDB
#   2. upload the same file again  -> expect still 1 TRIP item (idempotent)
# Usage: ./smoke_test.sh [path/to/YYYY-MM-DD_HH-MM-SS.csv]
# Writes under vehicle_id=smoketest so it never mixes with real data.
set -euo pipefail

STACK=DriveWiseStack
SAMPLE=${1:-../sample-data/2026-11-07_14-53-58.csv}
VEHICLE=smoketest

out() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
BUCKET=$(out RawBucketName)
TABLE=$(out TableName)
LOGS=$(out IngestLogGroupName)

NAME=$(basename "$SAMPLE")
DAY=${NAME:0:10}   # the handler takes the trip date from the key
KEY="raw/vehicle_id=$VEHICLE/date=$DAY/$NAME"

count() {  # count items for the vehicle whose SK starts with $1
  aws dynamodb query --table-name "$TABLE" --select COUNT --query Count \
    --key-condition-expression "PK = :pk AND begins_with(SK, :p)" \
    --expression-attribute-values "{\":pk\":{\"S\":\"VEH#$VEHICLE\"},\":p\":{\"S\":\"$1\"}}"
}

wait_for_log() {  # wait until the ingest log mentions $1 (up to ~60 s)
  for _ in $(seq 1 12); do
    if aws logs tail "$LOGS" --since 5m 2>/dev/null | grep -q "$1"; then return 0; fi
    sleep 5
  done
  echo "FAIL: no '$1' in $LOGS after 60 s"; aws logs tail "$LOGS" --since 5m || true; exit 1
}

echo "Uploading $NAME to s3://$BUCKET/$KEY"
aws s3 cp "$SAMPLE" "s3://$BUCKET/$KEY" --only-show-errors
wait_for_log '"status": "ingested"'
TRIPS=$(count "TRIP#"); SUMS=$(count "SUM#")
echo "after 1st upload: TRIP items=$TRIPS, SUM items=$SUMS"
[ "$TRIPS" = 1 ] && [ "$SUMS" -gt 0 ] || { echo "FAIL: expected 1 trip and some summaries"; exit 1; }

echo "Uploading the same file again"
aws s3 cp "$SAMPLE" "s3://$BUCKET/$KEY" --only-show-errors
wait_for_log '"status": "duplicate"'
TRIPS2=$(count "TRIP#")
echo "after 2nd upload: TRIP items=$TRIPS2"
[ "$TRIPS2" = 1 ] || { echo "FAIL: duplicate upload created a second trip"; exit 1; }

echo "PASS: ingest works and duplicate uploads are skipped"
