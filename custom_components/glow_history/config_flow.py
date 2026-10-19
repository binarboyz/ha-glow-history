"""Config and options flow for Glow History Import."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GlowApi, GlowApiError, GlowAuthError
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_ELEC_RATE,
    CONF_ELEC_STANDING,
    CONF_GAS_RATE,
    CONF_GAS_STANDING,
    CONF_INCLUDE_STANDING,
    CONF_LOOKBACK_DAYS,
    CONF_SCAN_HOURS,
    DEFAULT_OPTIONS,
    DOMAIN,
)


async def _validate(hass, username: str, password: str) -> str | None:
    """Return an error key, or None if the login works."""
    api = GlowApi(async_get_clientsession(hass), username, password)
    try:
        await api.authenticate()
    except GlowAuthError:
        return "invalid_auth"
    except GlowApiError:
        return "cannot_connect"
    return None


class GlowHistoryConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Bright login."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, username, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Glow ({username})",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    options=dict(DEFAULT_OPTIONS),
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            error = await _validate(
                self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return GlowHistoryOptionsFlow()


class GlowHistoryOptionsFlow(OptionsFlow):
    """Tariff and schedule settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        cur = {**DEFAULT_OPTIONS, **self.config_entry.options}
        money = vol.All(vol.Coerce(float), vol.Range(min=0, max=1000))
        schema = vol.Schema(
            {
                vol.Required(CONF_ELEC_RATE, default=cur[CONF_ELEC_RATE]): money,
                vol.Required(CONF_ELEC_STANDING, default=cur[CONF_ELEC_STANDING]): money,
                vol.Required(CONF_GAS_RATE, default=cur[CONF_GAS_RATE]): money,
                vol.Required(CONF_GAS_STANDING, default=cur[CONF_GAS_STANDING]): money,
                vol.Required(CONF_INCLUDE_STANDING, default=cur[CONF_INCLUDE_STANDING]): bool,
                vol.Required(CONF_SCAN_HOURS, default=cur[CONF_SCAN_HOURS]): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=24)
                ),
                vol.Required(CONF_LOOKBACK_DAYS, default=cur[CONF_LOOKBACK_DAYS]): vol.All(
                    vol.Coerce(int), vol.Range(min=2, max=30)
                ),
                vol.Required(CONF_BACKFILL_DAYS, default=cur[CONF_BACKFILL_DAYS]): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=1100)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
