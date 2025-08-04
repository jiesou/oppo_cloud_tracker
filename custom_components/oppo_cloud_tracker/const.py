"""Constants for oppo_cloud_tracker."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "oppo_cloud_tracker"
ATTRIBUTION = "Data provided by OPPO Cloud (HeyTap)"

# Default values
DEFAULT_SELENIUM_GRID_URL = "http://localhost:4444/wd/hub"
