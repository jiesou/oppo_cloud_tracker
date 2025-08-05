"""Constants for oppo_cloud_tracker."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "oppo_cloud_tracker"
ATTRIBUTION = "Data provided by OPPO Cloud (HeyTap)"

CONF_OPPO_CLOUD_FIND_URL = "https://cloud.oppo.com/pagemodule.html#/find"
CONF_OPPO_CLOUD_LOGIN_URL = "https://cloud.oppo.com/login.html"

# Default values
DEFAULT_SELENIUM_GRID_URL = "http://localhost:4444/wd/hub"

# Configuration keys
CONF_SELENIUM_GRID_URL = "selenium_grid_url"

# Services
SERVICE_LOCATE = "locate"

# Switch entity IDs
SWITCH_KEEP_SESSION = "keep_selenium_session"
