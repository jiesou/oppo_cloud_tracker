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
    from .data import OppoCloudDevice


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
    # coordinator.data is now list[OppoCloudDevice] directly
    devices = coordinator.data
    entities = [
        OppoCloudDeviceTracker(
            coordinator=coordinator,
            device_index=idx,
            device=device,
        )
        for idx, device in enumerate(devices)
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
        device_index: int,
        device: OppoCloudDevice,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator)
        self._device_index = device_index
        self._device = device
        # Generate a unique device ID based on device model and index
        device_id = f"{device.device_model}_{device_index}"
        self._device_id = device_id
        self._attr_name = device.device_model
        self._attr_unique_id = f"{DOMAIN}_{device_id}_tracker"

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        # Since we only have location names, not GPS coordinates
        return SourceType.GPS

    @property
    def location_name(self) -> str | None:
        """Return the location name where the device was last seen."""
        if self.coordinator.data and self._device_index < len(self.coordinator.data):
            device = self.coordinator.data[self._device_index]
            return device.location_name
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
    def is_connected(self) -> bool:
        """Return True if the device is connected."""
        if self.coordinator.data and self._device_index < len(self.coordinator.data):
            device = self.coordinator.data[self._device_index]
            return device.is_online
        return False

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the device state attributes."""
        attributes = {}

        if self.coordinator.data and self._device_index < len(self.coordinator.data):
            device = self.coordinator.data[self._device_index]

            # Add device-specific attributes from OppoCloudDevice
            # Dont add last_seen attribute because is updates frequently
            attributes["device_model"] = device.device_model
            attributes["is_online"] = str(device.is_online)

        return attributes
