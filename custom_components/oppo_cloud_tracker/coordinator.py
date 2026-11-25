"""DataUpdateCoordinator for oppo_cloud_tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    OppoCloudApiClientAuthenticationError,
    OppoCloudApiClientError,
    OppoCloudApiClientVerificationRequiredError,
)

if TYPE_CHECKING:
    from .data import OppoCloudConfigEntry, OppoCloudDevice


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class OppoCloudDataUpdateCoordinator(DataUpdateCoordinator[list["OppoCloudDevice"]]):
    """Class to manage fetching data from the OPPO Cloud API."""

    config_entry: OppoCloudConfigEntry

    async def _async_update_data(self) -> list[OppoCloudDevice]:
        """Update data via library."""
        try:
            return await self.config_entry.runtime_data.client.async_get_data()
        except OppoCloudApiClientVerificationRequiredError as exception:
            # Manual slider/graphic verification is pending. Credentials are
            # fine — do NOT trigger reauth. Surface a clear error state and
            # retry on the next scheduled update (the browser session is kept
            # alive so the user can complete the drag via noVNC meanwhile).
            raise UpdateFailed(exception) from exception
        except OppoCloudApiClientAuthenticationError as exception:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed(exception) from exception
        except OppoCloudApiClientError as exception:
            raise UpdateFailed(exception) from exception
