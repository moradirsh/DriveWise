"""S3 -> DynamoDB ingest.

Key layout expected: raw/vehicle_id=<id>/date=YYYY-MM-DD/<file>.csv
Idempotent: trip_id = sha256(file)[:16]; summaries are written first and the
TRIP item last (conditional put) as the commit marker, so a crash mid-way
leaves no trip item and a retry simply rewrites the same summaries.
"""
import hashlib
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import unquote_plus

try:
    from parse_car_scanner import parse_car_scanner_csv
    from trip_summary import summarize_trip
except ImportError:  # running from repo root (tests)
    from lambdas.ingest.parse_car_scanner import parse_car_scanner_csv
    from lambdas.ingest.trip_summary import summarize_trip

KEY_RE = re.compile(r"vehicle_id=([^/]+)/date=(\d{4}-\d{2}-\d{2})/")


class UnsupportedSource(Exception):
    pass


class BadKey(Exception):
    pass


def to_ddb(x):
    if isinstance(x, float):
        return Decimal(str(round(x, 6)))
    if isinstance(x, dict):
        return {k: to_ddb(v) for k, v in x.items()}
    if isinstance(x, list):
        return [to_ddb(v) for v in x]
    return x


def _first_line(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.readline()


def ingest_object(bucket, key, s3=None, table=None, tmp_dir="/tmp"):
    if s3 is None or table is None:
        import boto3
        s3 = s3 or boto3.client("s3")
        table = table or boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

    m = KEY_RE.search(key)
    if not m:
        raise BadKey(f"key does not match raw/vehicle_id=<id>/date=<date>/: {key}")
    vehicle_id, day = m.group(1), m.group(2)

    path = os.path.join(tmp_dir, hashlib.md5(key.encode()).hexdigest() + ".csv")
    s3.download_file(bucket, key, path)
    try:
        if [c.strip('"') for c in _first_line(path).strip().split(";")[:2]] != ["SECONDS", "PID"]:
            raise UnsupportedSource("only Car Scanner CSVs are supported so far")
        with open(path, "rb") as f:
            trip_id = hashlib.sha256(f.read()).hexdigest()[:16]
        pk = f"VEH#{vehicle_id}"

        parsed = parse_car_scanner_csv(path, start_date=date.fromisoformat(day))
        readings = parsed["readings"]
        if not readings:
            raise ValueError("no allowlisted readings in file")
        start_ms = min(r["timestamp_ms"] for r in readings)
        end_ms = max(r["timestamp_ms"] for r in readings)
        start_iso = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        trip_sk = f"TRIP#{start_iso}#{trip_id}"

        # cheap duplicate check (exact-key; the conditional put below is the real guard)
        existing = table.get_item(Key={"PK": pk, "SK": trip_sk}).get("Item")
        if existing:
            return {"status": "duplicate", "trip_id": trip_id}

        summary = summarize_trip(readings)
        with table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as bw:
            for param, s in summary.items():
                bw.put_item(Item=to_ddb({
                    "PK": pk, "SK": f"SUM#{trip_id}#{param}",
                    "trip_id": trip_id, "parameter": param,
                    "unit": s["unit"], "windows": s["windows"],
                    "start": start_iso,
                    "GSI1PK": f"{pk}#PARAM#{param}", "GSI1SK": start_iso,
                }))

        try:
            table.put_item(
                Item=to_ddb({
                    "PK": pk, "SK": trip_sk, "trip_id": trip_id,
                    "start": start_iso, "duration_s": int((end_ms - start_ms) / 1000),
                    "s3_key": key, "source": "car_scanner",
                    "n_readings": len(readings), "n_params": len(summary),
                    "dropped_params": len(parsed["dropped"]),
                }),
                ConditionExpression="attribute_not_exists(PK)",
            )
        except Exception as e:  # lost a race with a concurrent identical upload
            if "ConditionalCheckFailed" in str(e):
                return {"status": "duplicate", "trip_id": trip_id}
            raise
        return {"status": "ingested", "trip_id": trip_id, "params": len(summary)}
    finally:
        if os.path.exists(path):
            os.remove(path)


def handler(event, context=None):
    results = []
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        results.append(ingest_object(bucket, key))
    return results
