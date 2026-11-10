"""Collapse raw readings into min/max/mean/count per parameter per time bucket.

Raw data stays in S3; only these aggregates (or per-trip summaries) go to
DynamoDB. Text-valued readings are skipped (they can't be averaged).

bucket_seconds defaults to 1, but Car Scanner delivers only ~0.35-0.7 readings
per second per sensor, so a 1 s bucket is mostly empty; use 10 for that source.
The "second" key is the epoch second at the start of the bucket.
"""


def aggregate_per_second(readings, bucket_seconds=1):
    buckets = {}
    for r in readings:
        if r["value"] is None:
            continue
        start = (r["timestamp_ms"] // 1000) // bucket_seconds * bucket_seconds
        key = (r["parameter"], r["unit"], start)
        b = buckets.get(key)
        if b is None:
            buckets[key] = {"min": r["value"], "max": r["value"],
                            "sum": r["value"], "count": 1}
        else:
            b["min"] = min(b["min"], r["value"])
            b["max"] = max(b["max"], r["value"])
            b["sum"] += r["value"]
            b["count"] += 1

    out = []
    for (parameter, unit, second), b in sorted(buckets.items(), key=lambda kv: (kv[0][2], kv[0][0])):
        out.append({
            "parameter": parameter,
            "unit": unit,
            "second": second,
            "min": b["min"],
            "max": b["max"],
            "mean": b["sum"] / b["count"],
            "count": b["count"],
        })
    return out
