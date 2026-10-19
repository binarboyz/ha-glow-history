"""Glow History Import: imports Hildebrand Glow (DCC) readings into HA statistics."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import GlowApi, GlowApiError, GlowAuthError
from .const import DOMAIN
from .coordinator import GlowHistoryCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type GlowConfigEntry = ConfigEntry[GlowHistoryCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the import_now service."""

    async def _import_now(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.async_refresh()

    hass.services.async_register(DOMAIN, "import_now", _import_now)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Set up from a config entry."""
    api = GlowApi(
        async_get_clientsession(hass), entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    try:
        await api.authenticate()
    except GlowAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except GlowApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = GlowHistoryCoordinator(hass, entry, api)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The first run may backfill a year of data, so don't block startup on it.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN}_initial_import"
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlowConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: GlowConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
