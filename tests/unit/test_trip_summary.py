from lambdas.ingest.trip_summary import summarize_trip


def r(t_s, p, v, unit="x"):
    return {"timestamp_ms": t_s * 1000, "parameter": p, "unit": unit, "value": v}


def test_cold_engine_excluded_from_warm_windows():
    rs = [r(0, "coolant_temp_c", 40), r(0, "speed_kph", 0), r(0, "rpm", 800), r(1, "stft_b1_pct", 5)]
    s = summarize_trip(rs)["stft_b1_pct"]["windows"]
    assert "all" in s and "warm_idle" not in s


def test_warm_idle_and_cruise_windows():
    rs = [r(0, "coolant_temp_c", 90), r(0, "speed_kph", 0), r(0, "rpm", 800), r(1, "stft_b1_pct", 2.0)]
    rs += [r(100, "coolant_temp_c", 90), r(100, "speed_kph", 80), r(101, "speed_kph", 80.5), r(101, "rpm", 2000), r(102, "stft_b1_pct", -1.0)]
    w = summarize_trip(rs)["stft_b1_pct"]["windows"]
    assert w["warm_idle"]["median"] == 2.0
    assert w["warm_cruise"]["median"] == -1.0
    assert w["all"]["count"] == 2


def test_accelerating_is_not_cruise():
    rs = [r(0, "coolant_temp_c", 90), r(0, "speed_kph", 70), r(1, "speed_kph", 80), r(2, "stft_b1_pct", 3)]
    assert "warm_cruise" not in summarize_trip(rs)["stft_b1_pct"]["windows"]


def test_stale_context_ignored():
    rs = [r(0, "coolant_temp_c", 90), r(0, "speed_kph", 0), r(0, "rpm", 800), r(60, "stft_b1_pct", 2)]
    assert "warm_idle" not in summarize_trip(rs)["stft_b1_pct"]["windows"]
