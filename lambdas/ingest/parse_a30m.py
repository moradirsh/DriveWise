"""Adapter: XTool AnyScan A30M live-data CSV -> generic readings.

Input format (observed 2026-10-31):
  - first column has an empty header and holds epoch milliseconds
  - every other column header is "<parameter name>--<unit>"
  - a cell is blank until that parameter is first sampled, so blank means
    "no reading yet", never zero
  - the app repeats the last known value on every row, so row count overstates
    the true sampling rate of any single parameter

Output: a list of dicts {timestamp_ms, parameter, unit, value, value_text}.
Numeric cells fill `value`; non-numeric cells (e.g. "Off") fill `value_text`.
The vehicle_id is NOT in the file, so the caller attaches it.
"""
import csv


def parse_a30m_csv(path):
    readings = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.reader(f)
        header = next(rows)

        # split "Name--unit" on the LAST "--" so names containing it still work
        columns = []
        for h in header[1:]:
            name, sep, unit = h.rpartition("--")
            columns.append((name, unit) if sep else (h, ""))

        for row in rows:
            if not row or not row[0].strip():
                continue
            timestamp_ms = int(row[0])
            for (name, unit), cell in zip(columns, row[1:]):
                cell = cell.strip()
                if cell == "":
                    continue
                try:
                    value, value_text = float(cell), None
                except ValueError:
                    value, value_text = None, cell
                readings.append({
                    "timestamp_ms": timestamp_ms,
                    "parameter": name,
                    "unit": unit,
                    "value": value,
                    "value_text": value_text,
                })
    return readings
