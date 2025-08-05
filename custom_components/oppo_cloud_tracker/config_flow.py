"""Adds config flow for OPPO Cloud Tracker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from slugify import slugify

from .api import (
    OppoCloudApiClient,
    OppoCloudApiClientAuthenticationError,
    OppoCloudApiClientCommunicationError,
    OppoCloudApiClientError,
)
from .const import CONF_SELENIUM_GRID_URL, DEFAULT_SELENIUM_GRID_URL, DOMAIN, LOGGER


class OppoCloudFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for OPPO Cloud Tracker."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            try:
                await self._test_credentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    selenium_url=user_input[CONF_SELENIUM_GRID_URL],
                )
            except OppoCloudApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                _errors["base"] = "auth"
            except OppoCloudApiClientCommunicationError as exception:
                LOGGER.error(exception)
                _errors["base"] = "connection"
            except OppoCloudApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    # Use HeyTap username as unique identifier
                    unique_id=slugify(user_input[CONF_USERNAME])
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"OPPO Cloud - {user_input[CONF_USERNAME]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELENIUM_GRID_URL,
                        default=(user_input or {}).get(
                            CONF_SELENIUM_GRID_URL, DEFAULT_SELENIUM_GRID_URL
                        ),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.URL,
                        ),
                    ),
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def _test_credentials(
        self, username: str, password: str, selenium_url: str
    ) -> None:
        """Validate credentials."""
        # Test Selenium Grid connection and basic functionality
        client = OppoCloudApiClient(
            username=username,
            password=password,
            selenium_grid_url=selenium_url,
        )
        # Test connection to Selenium Grid
        await client.async_login_oppo_cloud()
        await client.async_cleanup()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for OPPO Cloud Tracker."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_SCAN_INTERVAL): vol.All(
                            vol.Coerce(int), vol.Range(min=30, max=3600)
                        ),
                    }
                ),
                self.config_entry.options,
            ),
        )
