"""Coordinator that runs the import on a schedule."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GlowApi, GlowApiError, GlowAuthError
from .const import CONF_SCAN_HOURS, DEFAULT_OPTIONS, DOMAIN, FUELS
from .importer import import_fuel

_LOGGER = logging.getLogger(__name__)


class GlowHistoryCoordinator(DataUpdateCoordinator[dict[str, datetime | None]]):
    """Fetches readings and writes statistics every few hours."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: GlowApi) -> None:
        options = {**DEFAULT_OPTIONS, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(hours=int(options[CONF_SCAN_HOURS])),
        )
        self.api = api
        self.options = options
        self.resources: dict[str, str] | None = None
        self.last_import: datetime | None = None
        self._lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, datetime | None]:
        async with self._lock:
            try:
                if self.resources is None:
                    found = await self.api.get_resources()
                    self.resources = {
                        fuel: found[cls] for fuel, cls in FUELS.items() if cls in found
                    }
                    if not self.resources:
                        self.resources = None
                        raise UpdateFailed(
                            "No electricity or gas consumption found on this Bright account"
                        )
                    _LOGGER.debug("Glowmarkt resources: %s", self.resources)
            except GlowAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except GlowApiError as err:
                raise UpdateFailed(str(err)) from err

            result = dict(self.data or {})
            errors: list[str] = []
            for fuel, resource_id in self.resources.items():
                try:
                    result[fuel] = await import_fuel(
                        self.hass, self.api, fuel, resource_id, self.options
                    )
                except GlowAuthError as err:
                    raise ConfigEntryAuthFailed(str(err)) from err
                except GlowApiError as err:
                    _LOGGER.warning("Importing %s failed: %s", fuel, err)
                    errors.append(f"{fuel}: {err}")

            if errors and len(errors) == len(self.resources):
                raise UpdateFailed("; ".join(errors))
            self.last_import = dt_util.utcnow()
            return result
