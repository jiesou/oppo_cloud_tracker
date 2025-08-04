"""Device tracker platform for OPPO Cloud Tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType

from .const import DOMAIN, LOGGER
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
    """Set up the device tracker platform."""
    coordinator = entry.runtime_data.coordinator

    # Wait for initial data to be loaded
    if not coordinator.data:
        LOGGER.warning(
            "No device data available yet, will add entities when data "
            "becomes available"
        )
        return

    # Create device tracker entities for each device found
    devices = coordinator.data.get("devices", [])
    entities = [
        OppoCloudDeviceTracker(
            coordinator=coordinator,
            device_id=device["device_id"],
            device_name=device["device_name"],
        )
        for device in devices
    ]

    if entities:
        async_add_entities(entities)
    else:
        LOGGER.warning("No devices found in coordinator data")


class OppoCloudDeviceTracker(OppoCloudEntity, TrackerEntity):
    """Representation of an OPPO Cloud device tracker."""

    def __init__(
        self,
        coordinator: OppoCloudDataUpdateCoordinator,
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
        # Since we only have location names, not GPS coordinates
        return SourceType.ROUTER

    @property
    def location_name(self) -> str | None:
        """Return the location name where the device was last seen."""
        if self.coordinator.data:
            devices = self.coordinator.data.get("devices", [])
            for device in devices:
                if device["device_id"] == self._device_id:
                    return device.get("location_name")
        return None

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        # We don't have GPS coordinates, only location names
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        # We don't have GPS coordinates, only location names
        return None

    @property
    def location_accuracy(self) -> int:
        """Return the location accuracy of the device."""
        # Since we only have location names, accuracy is not applicable
        return 0

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        if self.coordinator.data:
            devices = self.coordinator.data.get("devices", [])
            for device in devices:
                if device["device_id"] == self._device_id:
                    return device.get("battery_level")
        return None

    @property
    def is_connected(self) -> bool:
        """Return True if the device is connected."""
        if self.coordinator.data:
            devices = self.coordinator.data.get("devices", [])
            for device in devices:
                if device["device_id"] == self._device_id:
                    return device.get("is_online", False)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the device state attributes."""
        attributes = {}

        if self.coordinator.data:
            devices = self.coordinator.data.get("devices", [])
            for device in devices:
                if device["device_id"] == self._device_id:
                    # Add device-specific attributes
                    if "last_seen" in device:
                        attributes["last_seen"] = device["last_seen"]

                    if "device_model" in device:
                        attributes["device_model"] = device["device_model"]

                    if "is_online" in device:
                        attributes["is_online"] = device["is_online"]

                    break

        return attributes

    async def async_locate_device(self) -> None:
        """Trigger device location update."""
        LOGGER.info("Triggering location update for device: %s", self._device_name)
        # Call the find device API through coordinator
        # This should trigger the "find my phone" feature on OPPO Cloud
        await self.coordinator.async_request_refresh()
