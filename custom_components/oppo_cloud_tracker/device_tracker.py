"""Device tracker platform for OPPO Cloud Tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import callback

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
    """Set up the device tracker platform.

    Entity creation must not depend on data being present at setup time:
    the first fetch may fail (login in progress, manual verification
    pending) and return no devices. Entities are then added as soon as the
    coordinator delivers data — otherwise the registry entries registered
    earlier would stay orphaned ("entity no longer provided").
    """
    coordinator = entry.runtime_data.coordinator
    known_ids: set[str] = set()

    @callback
    def _add_entities_from_data() -> None:
        """Create tracker entities for any device not added yet."""
        if not coordinator.data:
            return
        new_entities = []
        for idx, device in enumerate(coordinator.data):
            # Keep the unique_id scheme stable so existing registry entries
            # (entity_id, user name/aliases, area, labels) are reused.
            unique_id = f"{DOMAIN}_{device.device_model}_{idx}_tracker"
            if unique_id in known_ids:
                continue
            known_ids.add(unique_id)
            new_entities.append(
                OppoCloudDeviceTracker(
                    coordinator=coordinator,
                    device_index=idx,
                    device=device,
                )
            )
        if new_entities:
            LOGGER.info(
                "Adding %d device tracker entities (total %d devices)",
                len(new_entities),
                len(coordinator.data),
            )
            async_add_entities(new_entities)

    # Add whatever is available now; subscribe for late-arriving data.
    _add_entities_from_data()
    if not known_ids:
        LOGGER.warning(
            "No device data at setup yet — entities will be created "
            "automatically when the first successful update arrives"
        )
    entry.async_on_unload(coordinator.async_add_listener(_add_entities_from_data))


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
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return WGS latitude value of the device."""
        if self.coordinator.data and self._device_index < len(self.coordinator.data):
            device = self.coordinator.data[self._device_index]
            return device.latitude
        return None

    @property
    def longitude(self) -> float | None:
        """Return WGS longitude value of the device."""
        if self.coordinator.data and self._device_index < len(self.coordinator.data):
            device = self.coordinator.data[self._device_index]
            return device.longitude
        return None

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

            # 将提取出来的中文文本作为参考地址存入属性
            if device.location_name:
                attributes["oppo_address"] = device.location_name

            # 将获取到的电量存入属性
            if device.battery_level is not None:
                attributes["battery_level"] = f"{device.battery_level}%"

        return attributes
