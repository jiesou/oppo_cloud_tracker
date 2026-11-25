"""Constants for oppo_cloud_tracker."""

import os
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "oppo_cloud_tracker"
ATTRIBUTION = "Data provided by OPPO Cloud (HeyTap)"

CONF_OPPO_CLOUD_FIND_URL = "https://cloud.oppo.com/pagemodule.html#/find"
CONF_OPPO_CLOUD_LOGIN_URL = "https://cloud.oppo.com/login.html"

# Default values
DEFAULT_REMOTE_BROWSER_URL = "http://localhost:4444/wd/hub"

# Configuration keys
CONF_REMOTE_BROWSER_URL = "selenium_grid_url"  # Legacy key name, keep for compatibility

# Services
SERVICE_LOCATE = "locate"
SERVICE_RESUME_VERIFICATION = "resume_verification"

# Switch entity IDs
SWITCH_KEEP_SESSION = "keep_browser_session"

# Login loop / retry policy (seconds unless noted)
LOGIN_LOOP_TIMEOUT = 60  # unified login loop deadline per attempt
MANUAL_VERIFY_TIMEOUT = 300  # how long a pending manual slider verification stays actionable
VERIFICATION_POLL_INTERVAL = 5  # poll interval while waiting for manual completion
LOGIN_RETRY_ATTEMPTS = 3  # transient-failure retries with a fresh session
LOGIN_RETRY_BACKOFF = 2  # seconds between retries
SESSION_MAX_AGE = 14 * 24 * 3600  # drop persisted session cookies older than this

# Verification detection patterns (text shown by the HeyTap verify widget)
VERIFY_TEXT_SLIDER = ("拖动", "滑块", "拼图", "拖拽", "按住", "滑动", "slide", "drag", "puzzle", "swipe")
VERIFY_TEXT_SECURITY = ("安全验证", "安全检查", "安全认证", "security verification", "verify you", "are you human")

# DOM fingerprints of common slider-behavior captcha widgets (TCaptcha /
# AJ-Captcha / NetEase / Alibaba nc / HeyTap own widget). Used only to
# DETECT the verification page so a human can complete it — never to solve it.
VERIFY_DOM_SELECTORS = (
    ".tcaptcha-drag",
    ".tc-slider",
    "#nc_1_wrapper",
    ".nc_iconfont",
    ".slide-verify",
    ".slide-verify-container",
    ".verify-bar",
    ".verify-move-block",
    ".captcha__slider",
    "[class*='slider-']",
    "[class*='slide-']",
    "[class*='drag-']",
)


def session_store_path(config_dir: str, username: str) -> str:
    """Return the cookie-session file path for an account.

    Keyed by a hash of the username (not the raw phone number) so the path
    contains no account information and is stable across config flow and
    runtime setup for the same account.
    """
    import hashlib

    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
    return os.path.join(config_dir, ".storage", f"{DOMAIN}_session_{digest}.json")
