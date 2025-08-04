"""Device tracker platform for OPPO Cloud Tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER
from .entity import IntegrationBlueprintEntity

if TYPE_CHECKING:
    from .coordinator import BlueprintDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the device tracker platform."""
    coordinator = entry.runtime_data.coordinator

    # Create device tracker entities for each device found
    entities = []

    # For now, create a single device tracker for the account
    # In production, iterate through discovered devices from coordinator data
    entities.append(
        OppoCloudDeviceTracker(
            coordinator=coordinator,
            device_id="primary_device",  # This should come from API data
            device_name="OPPO Device",  # This should come from API data
        )
    )

    async_add_entities(entities)


class OppoCloudDeviceTracker(IntegrationBlueprintEntity, TrackerEntity):
    """Representation of an OPPO Cloud device tracker."""

    def __init__(
        self,
        coordinator: BlueprintDataUpdateCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_name = device_name
        self._attr_unique_id = f"{DOMAIN}_{device_id}_tracker"

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        # TODO: Extract from coordinator data
        if self.coordinator.data:
            return self.coordinator.data.get("latitude")
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        # TODO: Extract from coordinator data
        if self.coordinator.data:
            return self.coordinator.data.get("longitude")
        return None

    @property
    def location_accuracy(self) -> int:
        """Return the location accuracy of the device."""
        # TODO: Extract from coordinator data or return default
        return 10  # meters

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        # TODO: Extract from coordinator data
        if self.coordinator.data:
            return self.coordinator.data.get("battery_level")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the device state attributes."""
        attributes = {}

        if self.coordinator.data:
            # Add any additional attributes from the API
            if "last_seen" in self.coordinator.data:
                attributes["last_seen"] = self.coordinator.data["last_seen"]

            if "device_model" in self.coordinator.data:
                attributes["device_model"] = self.coordinator.data["device_model"]

        return attributes

    async def async_locate_device(self) -> None:
        """Trigger device location update."""
        LOGGER.info("Triggering location update for device: %s", self._device_name)
        # TODO: Call the find device API through coordinator
        # This should trigger the "find my phone" feature on OPPO Cloud
        await self.coordinator.async_request_refresh()
