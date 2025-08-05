"""Custom types for oppo_cloud_tracker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import OppoCloudApiClient
    from .coordinator import OppoCloudDataUpdateCoordinator


type OppoCloudConfigEntry = ConfigEntry[OppoCloudData]


@dataclass
class OppoCloudData:
    """Data for the OPPO Cloud integration."""

    client: OppoCloudApiClient
    coordinator: OppoCloudDataUpdateCoordinator
    integration: Integration


@dataclass
class OppoCloudDevice:
    """Data for the OPPO Cloud devices."""

    device_model: str
    location_name: str
    latitude: float | None
    longitude: float | None
    battery_level: int
    last_seen: str | None
    is_online: bool
