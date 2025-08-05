"""Switch platform for OPPO Cloud Tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback

from .const import DOMAIN, SWITCH_KEEP_SESSION
from .entity import OppoCloudEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OppoCloudDataUpdateCoordinator


async def async_setup_entry(
    _: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = entry.runtime_data.coordinator

    # Create the keep session switch
    switch = OppoCloudKeepSessionSwitch(coordinator, entry)
    async_add_entities([switch])


class OppoCloudKeepSessionSwitch(OppoCloudEntity, SwitchEntity):
    """Switch to control whether to keep Selenium session between updates."""

    def __init__(
        self,
        coordinator: OppoCloudDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_name = "Keep Selenium Session"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{SWITCH_KEEP_SESSION}"
        self._attr_icon = "mdi:web"
        self._attr_entity_registry_enabled_default = True

        # Default to False (disabled) - cleanup session after each update
        self._is_on = False

        # Set the initial state in the API client
        self._update_api_client_setting()

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return self._is_on

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn the switch on."""
        self._is_on = True
        self._update_api_client_setting()
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        self._update_api_client_setting()
        self.async_write_ha_state()

    async def async_toggle(self, **_kwargs: Any) -> None:
        """Toggle the switch."""
        if self._is_on:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    @callback
    def _update_api_client_setting(self) -> None:
        """Update the API client with the current switch state."""
        client = self._config_entry.runtime_data.client
        client.set_keep_session(keep_session=self._is_on)
