"""Per-trip summaries, split by driving condition.

Fuel trims etc. only mean something when the engine is warm and the car is at
idle or steady cruise, so each parameter gets stats for three windows:
  all, warm_idle, warm_cruise.
Context (coolant, speed, rpm) is matched "as-of": the latest context sample at
or before the reading, ignored if older than CONTEXT_MAX_AGE_S.
"""
from bisect import bisect_right
from statistics import mean, median

WARM_COOLANT_C = 80.0
IDLE_SPEED_MAX = 1.0
IDLE_RPM = (400, 1100)
CRUISE_SPEED = (60.0, 110.0)
CRUISE_MAX_ACCEL = 1.0  # km/h per second
CONTEXT_MAX_AGE_S = 10


class _Series:
    def __init__(self, points):
        pts = sorted(points)
        self.t = [p[0] for p in pts]
        self.v = [p[1] for p in pts]

    def asof(self, t_ms):
        """Return (index, value) of latest sample <= t_ms and fresh enough, else None."""
        i = bisect_right(self.t, t_ms) - 1
        if i < 0 or t_ms - self.t[i] > CONTEXT_MAX_AGE_S * 1000:
            return None
        return i, self.v[i]


def _stats(values):
    return {"count": len(values), "mean": mean(values), "median": median(values),
            "min": min(values), "max": max(values)}


def summarize_trip(readings):
    by_param, units = {}, {}
    for r in readings:
        if r["value"] is None:
            continue
        by_param.setdefault(r["parameter"], []).append((r["timestamp_ms"], r["value"]))
        units[r["parameter"]] = r["unit"]

    coolant = _Series(by_param.get("coolant_temp_c", []))
    speed = _Series(by_param.get("speed_kph", []))
    rpm = _Series(by_param.get("rpm", []))

    out = {}
    for param, pts in by_param.items():
        windows = {"all": [], "warm_idle": [], "warm_cruise": []}
        for t, v in pts:
            windows["all"].append(v)
            c = coolant.asof(t)
            if c is None or c[1] < WARM_COOLANT_C:
                continue
            s = speed.asof(t)
            if s is None:
                continue
            si, sv = s
            r_ = rpm.asof(t)
            if (sv <= IDLE_SPEED_MAX and r_ is not None
                    and IDLE_RPM[0] <= r_[1] <= IDLE_RPM[1]
                    and (si == 0 or speed.v[si - 1] <= IDLE_SPEED_MAX)):
                windows["warm_idle"].append(v)
            elif CRUISE_SPEED[0] <= sv <= CRUISE_SPEED[1] and si > 0:
                dt = (speed.t[si] - speed.t[si - 1]) / 1000
                if 0 < dt <= CONTEXT_MAX_AGE_S:
                    accel = (sv - speed.v[si - 1]) / dt
                    if abs(accel) <= CRUISE_MAX_ACCEL:
                        windows["warm_cruise"].append(v)
        out[param] = {"unit": units[param],
                      "windows": {k: _stats(v) for k, v in windows.items() if v}}
    return out
