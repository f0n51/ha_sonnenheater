"""Config flow for Sonnen Heater integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_URL, DOMAIN


async def _test_connection(hass: HomeAssistant, url: str) -> None:
    """Raise if the server URL is not reachable."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()


class SonnenHeaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow for Sonnen Heater."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _test_connection(self.hass, user_input["url"])
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Sonnen Heater", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("url", default=DEFAULT_URL): str,
                    vol.Optional(
                        "scan_interval", default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(int, vol.Range(min=30)),
                }
            ),
            errors=errors,
        )
