import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "ingest"))

from parse_a30m import parse_a30m_csv
from aggregate import aggregate_per_second

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "sample-data",
                      "a30m_accessory_mode_2026-10-31.csv")


def write_csv(tmp_path, text):
    p = tmp_path / "t.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_header_split_keeps_name_and_unit(tmp_path):
    p = write_csv(tmp_path, ",Coolant Temp--deg C,Fuel Trim--%\n1000,80,1.5\n")
    names = {(r["parameter"], r["unit"]) for r in parse_a30m_csv(p)}
    assert names == {("Coolant Temp", "deg C"), ("Fuel Trim", "%")}


def test_blank_cells_are_skipped_not_zero(tmp_path):
    p = write_csv(tmp_path, ",A--V,B--V\n1000,1.0,\n1100,1.0,2.0\n")
    readings = parse_a30m_csv(p)
    b = [r for r in readings if r["parameter"] == "B"]
    assert len(b) == 1 and b[0]["value"] == 2.0


def test_text_values_go_to_value_text(tmp_path):
    p = write_csv(tmp_path, ",Fan--\n1000,Off\n")
    r = parse_a30m_csv(p)[0]
    assert r["value"] is None and r["value_text"] == "Off"


def test_aggregate_min_max_mean_per_second():
    readings = [
        {"timestamp_ms": 1000, "parameter": "A", "unit": "V", "value": 1.0, "value_text": None},
        {"timestamp_ms": 1500, "parameter": "A", "unit": "V", "value": 3.0, "value_text": None},
        {"timestamp_ms": 2100, "parameter": "A", "unit": "V", "value": 5.0, "value_text": None},
    ]
    agg = aggregate_per_second(readings)
    assert len(agg) == 2
    assert agg[0] == {"parameter": "A", "unit": "V", "second": 1,
                      "min": 1.0, "max": 3.0, "mean": 2.0, "count": 2}


def test_real_sample_file():
    readings = parse_a30m_csv(SAMPLE)
    assert len(readings) > 0
    assert {r["parameter"] for r in readings} >= {"Voltage Of Battery Positive"}
    agg = aggregate_per_second(readings)
    # ~19 s of data: far fewer aggregate rows than raw readings
    assert 0 < len(agg) < len(readings)
