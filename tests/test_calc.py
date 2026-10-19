"""Unit tests for calc.py using the user's real daily totals shape."""

from custom_components.glow_history.calc import accumulate, build_hourly, latest_data_ts

H = 3600


def test_trailing_zeros_trimmed_and_gaps_filled():
    start = 1_791_763_200  # 2026-10-12 00:00 UTC
    readings = {start: 0.2, start + 1800: 0.3, start + 3 * H: 0.1, start + 5 * H: 0.0}
    hours = build_hourly(readings, start, trim_leading=False)
    assert hours == [(start, 0.5), (start + H, 0.0), (start + 2 * H, 0.0), (start + 3 * H, 0.1)]


def test_leading_zeros_trimmed_on_first_run():
    start = 1_791_763_200
    readings = {start: 0.0, start + 2 * H: 0.4}
    assert build_hourly(readings, start, trim_leading=True) == [(start + 2 * H, 0.4)]
    assert build_hourly({start: 0.0}, start, trim_leading=True) == []


def test_cost_matches_tariff():
    hours = [(0, 1.0)] * 24  # 24 kWh in a day
    e, c = accumulate(hours, 10.0, 5.0, 24.47, 47.81, True)
    assert e[-1][2] == 34.0
    # 24 kWh x 24.47p + 47.81p standing = £6.3509
    assert abs((c[-1][2] - 5.0) - 6.3509) < 1e-6
    _, c2 = accumulate(hours, 0, 0, 24.47, 47.81, False)
    assert abs(c2[-1][2] - 5.8728) < 1e-6


def test_latest_data_ts():
    assert latest_data_ts({100: 0.0, 200: 0.1, 300: 0}) == 2000
    assert latest_data_ts({}) is None
