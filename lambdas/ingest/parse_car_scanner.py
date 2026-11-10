"""Adapter: Car Scanner ELM OBD2 CSV -> canonical readings.

Input format (observed 2026-11-05 to 2026-11-09):
  - semicolon-delimited, header `SECONDS;PID;VALUE;UNITS;` (trailing empty column)
  - one row per reading (long format)
  - SECONDS is seconds since local midnight, NOT epoch; the date comes from the
    filename (YYYY-MM-DD_HH-MM-SS.csv)
  - the recording includes every listed sensor plus many app-computed extras
    (fuel price, distance, averages...), so only an allowlist is kept
  - units are US customary (mph, psi, degrees F written as the single character
    U+2109), so every kept reading is converted to one canonical unit system

Unknown units on an allowlisted sensor raise ValueError (fail loudly) so a
changed app setting never silently corrupts baselines.
"""
import csv
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FILENAME_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_\d{2}-\d{2}-\d{2}")
STOICH_AFR = 14.7  # the app labels AFR-scaled values "equivalence ratio"

F = ("\u2109", "\u00b0F")  # the app writes degrees F as one character, U+2109

# source PID name -> (canonical name, accepted source units, canonical unit, converter)
ALLOWLIST = {
    "Engine coolant temperature": ("coolant_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Intake air temperature": ("intake_air_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Ambient air temperature": ("ambient_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Engine oil temperature": ("oil_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Battery Fluid Temperature": ("battery_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Catalyst temperature Bank 1 Sensor 1": ("catalyst_temp_c", F, "degC", lambda v: (v - 32) / 1.8),
    "Vehicle speed": ("speed_kph", ("mph",), "km/h", lambda v: v * 1.609344),
    "Engine RPM": ("rpm", ("rpm",), "rpm", lambda v: v),
    "Calculated engine load value": ("engine_load_pct", ("%",), "%", lambda v: v),
    "Throttle position": ("throttle_pct", ("%",), "%", lambda v: v),
    "Short term fuel % trim - Bank 1": ("stft_b1_pct", ("%",), "%", lambda v: v),
    "Long term fuel % trim - Bank 1": ("ltft_b1_pct", ("%",), "%", lambda v: v),
    "MAF air flow rate": ("maf_gps", ("kg/hour",), "g/s", lambda v: v / 3.6),
    "Intake manifold absolute pressure": ("map_kpa", ("psi",), "kPa", lambda v: v * 6.894757),
    "Barometric pressure": ("baro_kpa", ("psi",), "kPa", lambda v: v * 6.894757),
    "Fuel rail pressure (absolute)": ("fuel_rail_kpa", ("psi",), "kPa", lambda v: v * 6.894757),
    "Timing advance": ("timing_advance_deg", ("\u00b0",), "deg", lambda v: v),
    "Knock retard": ("knock_retard_deg", ("\u00b0",), "deg", lambda v: v),
    "Control module voltage": ("ctrl_module_v", ("V",), "V", lambda v: v),
    "Oxygen sensor 2 Bank 1 Voltage": ("o2_b1s2_v", ("V",), "V", lambda v: v),
    "Oxygen sensor 1 Wide Range Current (mA)": ("o2_b1s1_ma", ("mA",), "mA", lambda v: v),
    "Oxygen sensor 1 Wide Range Equivalence ratio": ("lambda_measured", ("",), "lambda", lambda v: v / STOICH_AFR),
    "Fuel/Air commanded equivalence ratio": ("lambda_commanded", ("",), "lambda", lambda v: v / STOICH_AFR),
    "Battery Estimated State of Charge": ("battery_soc_pct", ("%",), "%", lambda v: v),
    "Battery Internal Resistance": ("battery_resistance_mohm", ("Ohm",), "mOhm", lambda v: v * 1000),
}


def parse_car_scanner_csv(path, start_date=None, tz="America/Los_Angeles"):
    """Return {"readings": [...], "dropped": {name: count}, "skipped_non_numeric": n}.

    Each reading: {timestamp_ms (epoch), parameter (canonical), unit (canonical),
    value, value_text, source_name}. The vehicle_id is not in the file; the
    caller attaches it.
    """
    if start_date is None:
        m = FILENAME_DATE.search(os.path.basename(path))
        if not m:
            raise ValueError("no date in filename; pass start_date")
        start_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    midnight = datetime(start_date.year, start_date.month, start_date.day, tzinfo=ZoneInfo(tz))

    readings, dropped, skipped = [], {}, 0
    day_offset, prev_secs = 0, None
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.reader(f, delimiter=";")
        next(rows)  # header
        for row in rows:
            if len(row) < 4:
                continue
            try:
                secs = float(row[0])
            except ValueError:
                continue
            # seconds-since-midnight wraps to 0 after midnight
            if prev_secs is not None and secs < prev_secs - 43200:
                day_offset += 1
            prev_secs = secs

            name, raw, unit = row[1], row[2].strip(), row[3].strip()
            entry = ALLOWLIST.get(name)
            if entry is None:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            canonical, accepted_units, canonical_unit, convert = entry
            if unit not in accepted_units:
                raise ValueError(f"unexpected unit {unit!r} for {name!r}; expected {accepted_units}")
            try:
                value = convert(float(raw))
            except ValueError:
                skipped += 1  # e.g. "n/a"
                continue
            when = midnight + timedelta(days=day_offset, seconds=secs)
            readings.append({
                "timestamp_ms": int(when.timestamp() * 1000),
                "parameter": canonical,
                "unit": canonical_unit,
                "value": value,
                "value_text": None,
                "source_name": name,
            })
    return {"readings": readings, "dropped": dropped, "skipped_non_numeric": skipped}
