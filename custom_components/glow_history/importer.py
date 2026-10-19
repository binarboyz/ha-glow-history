"""Write Glowmarkt readings into Home Assistant long-term statistics."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import GlowApi
from .calc import accumulate, build_hourly, latest_data_ts
from .const import (
    CHUNK_DAYS,
    CONF_BACKFILL_DAYS,
    CONF_INCLUDE_STANDING,
    CONF_LOOKBACK_DAYS,
    DOMAIN,
    RATE_KEYS,
)

_LOGGER = logging.getLogger(__name__)


def stat_ids(fuel: str) -> tuple[str, str]:
    """Statistic IDs for (consumption, cost)."""
    return f"{DOMAIN}:{fuel}_consumption", f"{DOMAIN}:{fuel}_cost"


def _metadata(statistic_id: str, name: str, unit: str, unit_class: str | None) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


async def _last_row(hass: HomeAssistant, statistic_id: str) -> dict | None:
    rows = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    lst = rows.get(statistic_id) or []
    return lst[0] if lst else None


async def _sum_before(hass: HomeAssistant, statistic_id: str, before: datetime) -> float:
    """Running total of the last statistic row that starts before ``before``."""
    for days in (35, 400, 4000):
        rows = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            before - timedelta(days=days),
            before,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        lst = rows.get(statistic_id) or []
        if lst:
            return float(lst[-1].get("sum") or 0.0)
    return 0.0


async def import_fuel(
    hass: HomeAssistant,
    api: GlowApi,
    fuel: str,
    resource_id: str,
    options: dict[str, Any],
) -> datetime | None:
    """Import recent (or, on first run, historic) readings for one fuel.

    Returns the end time of the newest half-hour with real usage, if known.
    """
    energy_id, cost_id = stat_ids(fuel)
    now = dt_util.utcnow()
    last = await _last_row(hass, energy_id)

    if last is None:
        first_run = True
        last_start = None
        window_start = now - timedelta(days=int(options[CONF_BACKFILL_DAYS]))
    else:
        first_run = False
        last_start = _to_dt(last["start"])
        window_start = min(last_start, now) - timedelta(days=int(options[CONF_LOOKBACK_DAYS]))
    window_start = window_start.replace(minute=0, second=0, microsecond=0)

    await api.catchup(resource_id)

    readings: dict[int, float] = {}
    chunk_start = window_start
    while chunk_start < now:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), now)
        readings.update(await api.readings(resource_id, chunk_start, chunk_end))
        chunk_start = chunk_end
        if chunk_start < now:
            await asyncio.sleep(0.5)  # be gentle during backfill

    newest = latest_data_ts(readings)
    newest_dt = _to_dt(newest) if newest else None

    hours = build_hourly(readings, int(window_start.timestamp()), trim_leading=first_run)
    if not hours:
        _LOGGER.warning(
            "Glowmarkt returned no half-hourly %s usage between %s and %s", fuel, window_start, now
        )
        return newest_dt or (last_start + timedelta(hours=1) if last_start else None)

    if last_start is not None and hours[-1][0] < last_start.timestamp():
        # Glowmarkt returned less than we already hold - don't truncate history.
        _LOGGER.warning(
            "Glowmarkt returned %s data only up to %s, older than what is already "
            "imported (%s); skipping this run",
            fuel,
            _to_dt(hours[-1][0]),
            last_start,
        )
        return last_start + timedelta(hours=1)

    if first_run:
        base_energy = base_cost = 0.0
    else:
        start_dt = _to_dt(hours[0][0])
        base_energy = await _sum_before(hass, energy_id, start_dt)
        base_cost = await _sum_before(hass, cost_id, start_dt)

    rate_key, standing_key = RATE_KEYS[fuel]
    energy_rows, cost_rows = accumulate(
        hours,
        base_energy,
        base_cost,
        float(options[rate_key]),
        float(options[standing_key]),
        bool(options[CONF_INCLUDE_STANDING]),
    )

    label = fuel.capitalize()
    currency = hass.config.currency or "GBP"
    async_add_external_statistics(
        hass,
        _metadata(energy_id, f"Glow {label} consumption", "kWh", "energy"),
        [StatisticData(start=_to_dt(ts), state=v, sum=s) for ts, v, s in energy_rows],
    )
    async_add_external_statistics(
        hass,
        _metadata(cost_id, f"Glow {label} cost", currency, None),
        [StatisticData(start=_to_dt(ts), state=v, sum=s) for ts, v, s in cost_rows],
    )
    _LOGGER.info(
        "Imported %s hours of %s data (%s to %s)",
        len(energy_rows),
        fuel,
        _to_dt(energy_rows[0][0]),
        _to_dt(energy_rows[-1][0]),
    )
    return newest_dt
