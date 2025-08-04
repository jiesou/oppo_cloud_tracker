"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait


class OppoCloudApiClientError(Exception):
    """Exception to indicate a general API error."""


class OppoCloudApiClientCommunicationError(OppoCloudApiClientError):
    """Exception to indicate a communication error."""


class OppoCloudApiClientAuthenticationError(OppoCloudApiClientError):
    """Exception to indicate an authentication error."""


class OppoCloudApiClient:
    """OPPO Cloud (HeyTap) API Client using Selenium."""

    def __init__(
        self,
        username: str,
        password: str,
        selenium_grid_url: str,
    ) -> None:
        """Initialize OPPO Cloud API Client."""
        self._username = username
        self._password = password
        self._selenium_grid_url = selenium_grid_url
        self._driver: webdriver.Remote | None = None

    async def async_get_data(self) -> dict[str, Any]:
        """Get device location data from OPPO Cloud."""
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._get_device_locations
            )
        except WebDriverException as exception:
            msg = f"Selenium WebDriver error - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception
        except TimeoutException as exception:
            msg = f"Timeout error accessing OPPO Cloud - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected error getting device data - {exception}"
            raise OppoCloudApiClientError(msg) from exception

    def _get_device_locations(self) -> dict[str, Any]:
        """Get device locations using Selenium WebDriver."""
        driver = None
        try:
            # Set up Chrome options for headless mode
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")

            # Create remote WebDriver instance
            driver = webdriver.Remote(
                command_executor=self._selenium_grid_url,
                options=chrome_options,
            )

        except TimeoutException as exception:
            msg = "Timeout waiting for page elements"
            raise OppoCloudApiClientCommunicationError(msg) from exception
        except NoSuchElementException as exception:
            msg = "Required page elements not found - possible login failure"
            raise OppoCloudApiClientAuthenticationError(msg) from exception
        else:
            # For now, return fake data until actual implementation
            return {
                "devices": [
                    {
                        "device_id": "device_001",
                        "device_name": "OPPO Find X7",
                        "location_name": "家里",  # Home in Chinese
                        "battery_level": 85,
                        "last_seen": "2024-01-15T10:30:00Z",
                        "device_model": "OPPO Find X7",
                        "is_online": True,
                    },
                    {
                        "device_id": "device_002",
                        "device_name": "OPPO Reno12",
                        "location_name": "公司",  # Company in Chinese
                        "battery_level": 42,
                        "last_seen": "2024-01-15T09:45:00Z",
                        "device_model": "OPPO Reno12",
                        "is_online": False,
                    },
                ]
            }
        finally:
            if driver:
                driver.quit()

    async def async_test_connection(self) -> bool:
        """Test connection to Selenium Grid and basic functionality."""
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._test_selenium_connection
            )
        except Exception as exception:
            msg = f"Connection test failed - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception

    def _test_selenium_connection(self) -> bool:
        """Test Selenium Grid connection."""
        driver = None
        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")

            driver = webdriver.Remote(
                command_executor=self._selenium_grid_url,
                options=chrome_options,
            )

            # Simple test - navigate to a basic page
            driver.get("https://www.google.com")
            WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
            )
            return True

        finally:
            if driver:
                driver.quit()

    # Keep compatibility with existing template methods
    async def async_set_title(self, _: str) -> Any:
        """Compatibility method - not used for OPPO Cloud."""
        # This method exists for template compatibility but isn't needed
        # for device tracking functionality
        return {
            "status": "not_implemented",
            "message": "Not applicable for device tracking",
        }
