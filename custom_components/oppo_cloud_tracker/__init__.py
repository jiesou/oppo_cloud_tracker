"""Custom integration to integrate oppo_cloud_tracker with Home Assistant.

For more details about this integration, please refer to
https://github.com/jiesou/oppo_cloud_tracker
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.loader import async_get_loaded_integration

from .api import OppoCloudApiClient
from .const import CONF_SELENIUM_GRID_URL, DOMAIN, LOGGER, SERVICE_LOCATE
from .coordinator import OppoCloudDataUpdateCoordinator
from .data import OppoCloudData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import OppoCloudConfigEntry

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
]


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: OppoCloudConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    # Get scan interval from options, default to 300 seconds (5 minutes)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 300)

    coordinator = OppoCloudDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        config_entry=entry,
        # Should pass the config entry explicitly
        # See: https://github.com/home-assistant/core/blob/35025c4b598dea294f0db254e8c872f082447f42/homeassistant/helpers/update_coordinator.py#L90-L97
        update_interval=timedelta(seconds=scan_interval),
        always_update=False,  # OppoCloudDevice can directly handle __eq__
    )
    entry.runtime_data = OppoCloudData(
        client=OppoCloudApiClient(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            selenium_grid_url=entry.data[CONF_SELENIUM_GRID_URL],
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Register the locate service
    async def async_locate_service(_: ServiceCall) -> None:
        """Handle the locate service call."""
        LOGGER.info("Locate service called, triggering device location update")
        try:
            await coordinator.async_refresh()
        except Exception as err:
            LOGGER.error("Failed to update device locations: %s", err)
            error_msg = f"Failed to update device locations: {err}"
            raise ServiceValidationError(error_msg) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOCATE,
        async_locate_service,
        schema=vol.Schema({}),
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: OppoCloudConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    # Clean up WebDriver resources
    if entry.runtime_data and entry.runtime_data.client:
        await entry.runtime_data.client.async_cleanup()

    # Remove the locate service
    hass.services.async_remove(DOMAIN, SERVICE_LOCATE)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: OppoCloudConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
