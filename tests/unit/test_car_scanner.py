import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "ingest"))

from parse_car_scanner import parse_car_scanner_csv, ALLOWLIST
from aggregate import aggregate_per_second

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "sample-data", "2026-11-07_14-53-58.csv")
HEADER = "SECONDS;PID;VALUE;UNITS;\n"


def write_csv(tmp_path, rows, name="2026-11-07_14-53-58.csv"):
    p = tmp_path / name
    p.write_text(HEADER + "".join(rows), encoding="utf-8")
    return str(p)


def test_converts_units(tmp_path):
    p = write_csv(tmp_path, [
        "53649.0;Engine coolant temperature;212;\u2109;\n",
        "53649.0;Vehicle speed;62.137119;mph;\n",
        "53649.0;Intake manifold absolute pressure;14.503774;psi;\n",
        "53649.0;MAF air flow rate;36;kg/hour;\n",
        "53649.0;Fuel/Air commanded equivalence ratio;14.7;;\n",
    ])
    got = {r["parameter"]: r["value"] for r in parse_car_scanner_csv(p)["readings"]}
    assert got["coolant_temp_c"] == pytest.approx(100.0)
    assert got["speed_kph"] == pytest.approx(100.0, rel=1e-4)
    assert got["map_kpa"] == pytest.approx(100.0, rel=1e-4)
    assert got["maf_gps"] == pytest.approx(10.0)
    assert got["lambda_commanded"] == pytest.approx(1.0)


def test_drops_unlisted_sensors_and_counts_them(tmp_path):
    p = write_csv(tmp_path, [
        "53649.0;Engine RPM;800;rpm;\n",
        "53649.0;Fuel used price;0.04;$;\n",
        "53650.0;Fuel used price;0.05;$;\n",
    ])
    res = parse_car_scanner_csv(p)
    assert [r["parameter"] for r in res["readings"]] == ["rpm"]
    assert res["dropped"] == {"Fuel used price": 2}


def test_unexpected_unit_fails_loudly(tmp_path):
    p = write_csv(tmp_path, ["53649.0;Vehicle speed;50;km/h;\n"])
    with pytest.raises(ValueError):
        parse_car_scanner_csv(p)


def test_non_numeric_value_is_skipped(tmp_path):
    p = write_csv(tmp_path, ["53649.0;Short term fuel % trim - Bank 1;n/a;%;\n"])
    res = parse_car_scanner_csv(p)
    assert res["readings"] == [] and res["skipped_non_numeric"] == 1


def test_timestamp_uses_filename_date_and_midnight_seconds(tmp_path):
    p = write_csv(tmp_path, ["53649.5;Engine RPM;800;rpm;\n"])
    ts = parse_car_scanner_csv(p)["readings"][0]["timestamp_ms"]
    when = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo("America/Los_Angeles"))
    assert (when.year, when.month, when.day, when.hour, when.minute) == (2026, 11, 7, 14, 54)


def test_midnight_rollover_advances_the_day(tmp_path):
    p = write_csv(tmp_path, [
        "86399.0;Engine RPM;800;rpm;\n",
        "1.0;Engine RPM;810;rpm;\n",
    ])
    a, b = parse_car_scanner_csv(p)["readings"]
    assert b["timestamp_ms"] - a["timestamp_ms"] == 2000


def test_real_sample_has_all_allowlisted_sensors():
    res = parse_car_scanner_csv(SAMPLE)
    canonical = {r["parameter"] for r in res["readings"]}
    assert canonical == {entry[0] for entry in ALLOWLIST.values()}
    coolant = [r["value"] for r in res["readings"] if r["parameter"] == "coolant_temp_c"]
    assert 80 < min(coolant) and max(coolant) < 95
    assert "Fuel used price" in res["dropped"]


def test_ten_second_buckets_are_denser_than_one_second():
    readings = parse_car_scanner_csv(SAMPLE)["readings"]
    one = aggregate_per_second(readings, 1)
    ten = aggregate_per_second(readings, 10)
    assert len(ten) < len(one)
    assert max(b["count"] for b in ten) > max(b["count"] for b in one)
