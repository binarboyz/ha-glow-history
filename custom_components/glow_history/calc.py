"""Pure calculation helpers (no Home Assistant imports, so they can be unit tested)."""

from __future__ import annotations

from collections import defaultdict

HOUR = 3600


def build_hourly(
    readings: dict[int, float], start_ts: int, trim_leading: bool
) -> list[tuple[int, float]]:
    """Turn half-hourly readings into a continuous list of (hour_start_ts, kWh).

    - Slots before ``start_ts`` are ignored.
    - The list ends at the last hour that has real (non-zero) usage, because
      Glowmarkt reports data that has not arrived yet as 0. Those trailing
      hours are written on a later run once the data turns up.
    - With ``trim_leading`` (first ever import) the list starts at the first
      hour with usage, so no standing charge is added for months before your
      data begins. Otherwise it starts exactly at ``start_ts`` to keep the
      running totals continuous.
    - Gaps in between are filled with 0.
    """
    hourly: dict[int, float] = defaultdict(float)
    for ts, value in readings.items():
        if value is None or value < 0 or ts < start_ts:
            continue
        hourly[ts - ts % HOUR] += float(value)

    positive = [h for h, v in hourly.items() if v > 0]
    if not positive:
        return []

    first = min(positive) if trim_leading else start_ts - start_ts % HOUR
    last = max(positive)
    return [
        (h, round(hourly.get(h, 0.0), 6)) for h in range(first, last + HOUR, HOUR)
    ]


def accumulate(
    hours: list[tuple[int, float]],
    base_energy: float,
    base_cost: float,
    rate_p_per_kwh: float,
    standing_p_per_day: float,
    include_standing: bool,
) -> tuple[list[tuple[int, float, float]], list[tuple[int, float, float]]]:
    """Return (energy_rows, cost_rows) as (hour_ts, value_this_hour, running_sum).

    Cost is in pounds: kWh x unit rate, plus 1/24 of the daily standing charge
    for every hour (if enabled).
    """
    standing_per_hour = standing_p_per_day / 100 / 24 if include_standing else 0.0
    energy_sum = base_energy
    cost_sum = base_cost
    energy_rows: list[tuple[int, float, float]] = []
    cost_rows: list[tuple[int, float, float]] = []
    for hour_ts, kwh in hours:
        cost = kwh * rate_p_per_kwh / 100 + standing_per_hour
        energy_sum += kwh
        cost_sum += cost
        energy_rows.append((hour_ts, kwh, round(energy_sum, 6)))
        cost_rows.append((hour_ts, round(cost, 6), round(cost_sum, 6)))
    return energy_rows, cost_rows


def latest_data_ts(readings: dict[int, float]) -> int | None:
    """End time (epoch) of the newest half-hour slot with real usage."""
    slots = [ts for ts, v in readings.items() if v]
    return max(slots) + 1800 if slots else None
