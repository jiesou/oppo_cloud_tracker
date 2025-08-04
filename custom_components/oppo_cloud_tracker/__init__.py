"""
Custom integration to integrate oppo_cloud_tracker with Home Assistant.

For more details about this integration, please refer to
https://github.com/jiesou/oppo_cloud_tracker
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.loader import async_get_loaded_integration

from .api import OppoCloudApiClient
from .const import CONF_SELENIUM_GRID_URL, DOMAIN, LOGGER
from .coordinator import OppoCloudDataUpdateCoordinator
from .data import OppoCloudData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import OppoCloudConfigEntry

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
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
        update_interval=timedelta(seconds=scan_interval),
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

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: OppoCloudConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: OppoCloudConfigEntry,
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
