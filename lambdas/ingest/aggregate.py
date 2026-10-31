"""Collapse raw readings into per-second min/max/mean/count per parameter.

Raw ~10 Hz data stays in S3; only these aggregates go to DynamoDB.
Text-valued readings are skipped (they can't be averaged).
"""


def aggregate_per_second(readings):
    buckets = {}
    for r in readings:
        if r["value"] is None:
            continue
        key = (r["parameter"], r["unit"], r["timestamp_ms"] // 1000)
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
