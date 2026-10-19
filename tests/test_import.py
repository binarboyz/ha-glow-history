"""End-to-end test with a real recorder and a fake Glowmarkt API."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.glow_history.const import DEFAULT_OPTIONS, DOMAIN

ELEC = "elec-res"
GAS = "gas-res"
UTC = timezone.utc


class FakeApi:
    """Serves half-hourly data up to a moving 'available_until' time."""

    available_until: datetime

    def __init__(self, *_args):
        self.calls = 0

    async def authenticate(self):
        return None

    async def get_resources(self):
        return {"electricity.consumption": ELEC, "gas.consumption": GAS, "x.cost": "c"}

    async def catchup(self, _rid):
        return None

    async def readings(self, rid, start, end):
        self.calls += 1
        out = {}
        t = start
        while t < end:
            ts = int(t.timestamp())
            # data not yet "arrived" is reported as 0, like Glowmarkt does
            if t < FakeApi.available_until:
                out[ts] = 0.25 if rid == ELEC else 0.5  # 0.5 / 1.0 kWh per hour
            else:
                out[ts] = 0.0
            t += timedelta(minutes=30)
        return out


async def _stats(hass, sid, start):
    from homeassistant.components.recorder import get_instance

    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, None, {sid}, "hour", None, {"sum", "state"}
    )
    return rows.get(sid, [])


async def test_backfill_then_late_data(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    freezer.move_to(now)
    # history starts 10 days ago; data available up to 2 days ago
    data_start = now - timedelta(days=10)
    FakeApi.available_until = now - timedelta(days=2)

    opts = dict(DEFAULT_OPTIONS)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "a@b.c", "password": "x"},
        options=opts,
        unique_id="a@b.c",
    )
    entry.add_to_hass(hass)

    real_readings = FakeApi.readings

    gas_start = data_start + timedelta(days=3)

    async def readings_from_start(self, rid, start, end):
        # Gas history starts later; earlier chunks get a 404 like the real API
        if rid == GAS and end <= gas_start:
            return {}  # what GlowApi.readings returns after a 404
        first = data_start if rid == ELEC else gas_start
        return await real_readings(self, rid, max(start, first), end)

    async def no_sleep(_s):
        return None

    with patch("custom_components.glow_history.GlowApi", FakeApi), patch.object(
        FakeApi, "readings", readings_from_start
    ), patch("custom_components.glow_history.importer.asyncio.sleep", no_sleep):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        elec = await _stats(hass, "glow_history:electricity_consumption", data_start - timedelta(days=1))
        cost = await _stats(hass, "glow_history:electricity_cost", data_start - timedelta(days=1))
        # 8 days of data = 192 hours, 0.5 kWh each
        assert len(elec) == 192, len(elec)
        assert elec[0]["sum"] == pytest.approx(0.5)
        assert elec[-1]["sum"] == pytest.approx(96.0)
        per_hour_cost = 0.5 * 24.47 / 100 + 47.81 / 100 / 24
        assert cost[-1]["sum"] == pytest.approx(192 * per_hour_cost, rel=1e-6)
        gas = await _stats(hass, "glow_history:gas_consumption", data_start - timedelta(days=1))
        assert len(gas) == 192 - 72, len(gas)
        assert gas[-1]["sum"] == pytest.approx(120.0)

        sensor = hass.states.get("sensor.glow_history_import_electricity_data_available_up_to")
        assert sensor is not None and sensor.state not in ("unknown", "unavailable")

        # A day later, one more day of data has arrived
        now2 = now + timedelta(days=1)
        freezer.move_to(now2)
        FakeApi.available_until = now2 - timedelta(days=2) + timedelta(days=1)  # 2 more days
        await hass.services.async_call(DOMAIN, "import_now", blocking=True)
        await hass.async_block_till_done(wait_background_tasks=True)
        await async_wait_recording_done(hass)

        elec = await _stats(hass, "glow_history:electricity_consumption", data_start - timedelta(days=1))
        assert len(elec) == 192 + 48, len(elec)
        sums = [r["sum"] for r in elec]
        # running total is continuous and strictly increasing by 0.5 each hour
        assert all(b - a == pytest.approx(0.5) for a, b in zip(sums, sums[1:]))
        assert sums[-1] == pytest.approx(120.0)

        # Changing options reloads cleanly
        hass.config_entries.async_update_entry(entry, options={**opts, "gas_unit_rate": 8.0})
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED


async def test_api_readings_404_is_empty(hass: HomeAssistant, aioclient_mock) -> None:
    """A real HTTP 404 from Glowmarkt becomes an empty period, not a failure."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.glow_history.api import GlowApi, GlowApiError
    from custom_components.glow_history.const import API_BASE

    aioclient_mock.post(f"{API_BASE}/auth", json={"valid": True, "token": "t", "exp": 9999999999})
    aioclient_mock.get(f"{API_BASE}/resource/gas/readings", status=404)
    aioclient_mock.get(
        f"{API_BASE}/resource/elec/readings", json={"data": [[1791763200, 0.3], [1791765000, None]]}
    )
    aioclient_mock.get(f"{API_BASE}/resource/bad/readings", status=500)

    api = GlowApi(async_get_clientsession(hass), "u", "p")
    start = datetime(2026, 10, 12, tzinfo=UTC)
    end = start + timedelta(days=1)
    assert await api.readings("gas", start, end) == {}
    assert await api.readings("elec", start, end) == {1791763200: 0.3}
    with patch("custom_components.glow_history.api.asyncio.sleep") as sleep:
        sleep.return_value = None

        async def _noop(*_a):
            return None

        sleep.side_effect = _noop
        with pytest.raises(GlowApiError):
            await api.readings("bad", start, end)
