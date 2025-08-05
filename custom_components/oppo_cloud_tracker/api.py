"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.remote_connection import RemoteConnection

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webelement import WebElement

from custom_components.oppo_cloud_tracker.const import (
    CONF_OPPO_CLOUD_FIND_URL,
    CONF_OPPO_CLOUD_LOGIN_URL,
    LOGGER,
)
from custom_components.oppo_cloud_tracker.data import OppoCloudDevice


class OppoCloudApiClientError(Exception):
    """Exception to indicate a general API error."""

    def __init__(self, message: str = "unexpected") -> None:
        """Initialize the OppoCloudApiClientError with a message."""
        super().__init__(message)


class OppoCloudApiClientSeleniumTimeoutError(OppoCloudApiClientError):
    """Exception to indicate a timeout error."""

    def __init__(self, context: str = "unexpected") -> None:
        """Initialize the OppoCloudApiClientSeleniumTimeoutError with a message."""
        super().__init__(f"when {context}")


class OppoCloudApiClientCommunicationError(OppoCloudApiClientError):
    """Exception to indicate a communication with Selenium error."""

    def __init__(self, context: str = "unexpected") -> None:
        """Initialize the OppoCloudApiClientCommunicationError with a message."""
        super().__init__(f"when {context}")


class OppoCloudApiClientAuthenticationError(OppoCloudApiClientError):
    """Exception to indicate an authentication error."""

    def __init__(self, context: str = "unexpected") -> None:
        """Initialize the OppoCloudApiClientAuthenticationError with a message."""
        super().__init__(f"when {context}")


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
        self._driver_initialized = False
        self._keep_session = False  # Default to False for resource efficiency

    def set_keep_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the WebDriver session between updates."""
        self._keep_session = keep_session
        # If disabling session keeping and we have an active session, clean it up
        if not keep_session and self._driver is not None and self._driver_initialized:
            self._cleanup_driver()

    def _get_or_create_driver(self) -> webdriver.Remote:
        """Get existing WebDriver instance or create a new one."""
        if self._driver is not None and self._driver_initialized:
            return self._driver

        try:
            # Set up Chrome options for headless mode
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")

            remote_connection = RemoteConnection(self._selenium_grid_url)
            remote_connection.set_timeout(3)  # seconds
            self._driver = webdriver.Remote(
                command_executor=remote_connection,
                options=chrome_options,
            )
            self._driver_initialized = True
        except Exception:
            self._driver = None
            self._driver_initialized = False
            raise
        return self._driver

    async def async_cleanup(self) -> None:
        """Clean up WebDriver resources."""
        if not self._driver:
            return
        await asyncio.get_event_loop().run_in_executor(None, self._cleanup_driver)

    def _cleanup_driver(self) -> None:
        """Clean up the WebDriver instance."""
        if not self._driver:
            return
        try:
            self._driver.quit()
        except WebDriverException:
            # Ignore WebDriver cleanup errors as they're expected during shutdown
            pass
        finally:
            self._driver = None
            self._driver_initialized = False

    async def async_login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Selenium."""
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._login_oppo_cloud)
        except TimeoutException as exception:
            msg = f"login - {exception}"
            raise OppoCloudApiClientSeleniumTimeoutError(msg) from exception
        except Exception as exception:
            msg = f"login - {exception}"
            raise OppoCloudApiClientAuthenticationError(msg) from exception

    def _login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Selenium."""
        driver = self._get_or_create_driver()

        driver.get(CONF_OPPO_CLOUD_LOGIN_URL)

        # "Sign in"
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, "div.wrapper-login span.btn")
            )
        ).click()

        login_iframe = WebDriverWait(driver, 10).until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "iframe"))
        )
        driver.switch_to.frame(login_iframe)

        # Enter tele and password
        WebDriverWait(driver, 10).until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, "div:nth-child(1) > form input[type='tel']")
            )
        ).send_keys(self._username)
        driver.find_element(
            By.CSS_SELECTOR, "div:nth-child(1) > form input[type='password']"
        ).send_keys(self._password)
        # Wait for "Sign in with password" button
        WebDriverWait(driver, 10).until(
            lambda d: not any(
                "disabled" in cls
                for cls in (
                    (
                        d.find_element(
                            By.CSS_SELECTOR, "div:nth-child(1) > form button"
                        ).get_attribute("class")
                        or ""
                    ).split()
                )
            )
        )
        driver.find_element(By.CSS_SELECTOR, "div:nth-child(1) > form button").click()
        # Wait for login to complete
        WebDriverWait(driver, 10).until(
            expected_conditions.url_changes(CONF_OPPO_CLOUD_LOGIN_URL)
        )

    async def async_get_data(self) -> list[OppoCloudDevice]:
        """Get device location data from OPPO Cloud."""
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._get_devices_data
            )
        except OppoCloudApiClientAuthenticationError:
            # Not logged in, try to log in
            LOGGER.info("OPPO Cloud not logged in, attempting to log in")
            await self.async_login_oppo_cloud()
            return await self.async_get_data()
        except TimeoutException as exception:
            msg = f"get_devices_data - {exception}"
            raise OppoCloudApiClientSeleniumTimeoutError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        else:
            # If not keeping session, cleanup after successful data fetch
            if not self._keep_session:
                await self.async_cleanup()
            return result

    def _get_devices_data(self) -> list[OppoCloudDevice]:
        """Get device locations using Selenium WebDriver."""
        driver = self._get_or_create_driver()
        driver.get(CONF_OPPO_CLOUD_FIND_URL)

        # Wait for the page to load and check if logged in
        WebDriverWait(driver, 10).until(
            lambda d: (
                d.find_elements(By.CSS_SELECTOR, "#device-list > div.device-list")
                or d.find_elements(By.CSS_SELECTOR, "div.wrapper-login span.btn")
            )
        )

        # If redirected to login page
        if not driver.current_url.startswith(CONF_OPPO_CLOUD_FIND_URL):
            msg = "not logged in or page redirected unexpectedly"
            raise OppoCloudApiClientAuthenticationError(msg)

        # Wait for the device list to fully load
        # Step 1: Wait for device_location loading indicator
        WebDriverWait(driver, 10).until(
            lambda d: d.find_element(
                By.CSS_SELECTOR, "div.device_location"
            ).value_of_css_property("display")
            == "none"
        )
        # Step 2: Wait for all "正在更新" indicators to disappear
        WebDriverWait(driver, 30).until(
            lambda d: not d.find_elements(By.XPATH, "//span[text()='正在更新']")
        )
        # Step 3: Wait for device location info to be present
        WebDriverWait(driver, 10).until(
            lambda d: all(
                # Each device should has device-poi (location info) or in error state
                item.find_elements(By.CSS_SELECTOR, ".device-poi")
                or item.find_elements(
                    By.CSS_SELECTOR, ".device-status-wrap:not(.positioning)"
                )
                for item in d.find_elements(
                    By.CSS_SELECTOR, "#device-list .device-list ul > li"
                )
            )
            if d.find_elements(By.CSS_SELECTOR, "#device-list .device-list ul > li")
            else True
        )

        devices_list_el = driver.find_element(
            By.CSS_SELECTOR, "#device-list > div.device-list"
        )

        devices: list[OppoCloudDevice] = []
        # Find all device items
        device_items = devices_list_el.find_elements(By.CSS_SELECTOR, "ul > li")
        for item in device_items:
            item.click()
            # To check device details
            device_detail_el = WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.panel-wrap > div.device-detail")
                )
            )
            devices.append(self._parse_single_device(device_detail_el))
            # Go back to the device list
            device_detail_el.find_element(
                By.CSS_SELECTOR,
                "div.handle-header-left > i.back",
            ).click()
        return devices

    def _parse_single_device(self, device_el: WebElement) -> OppoCloudDevice:
        """Parse a single device element."""
        # Device model/name
        name_el = device_el.find_element(
            By.CSS_SELECTOR, ".device-name span:last-child"
        )
        device_model = name_el.text.strip()

        # Check is_online
        online_el = device_el.find_element(By.CSS_SELECTOR, ".device-name .device-dian")
        class_attr = online_el.get_attribute("class")
        is_online = class_attr is not None and "online" in class_attr

        # Check location_name and last_seen
        address_el = device_el.find_element(By.CSS_SELECTOR, ".device-address")
        # "XX地 · 刚刚"
        address_text = address_el.text.strip()
        if "·" in address_text:
            location_name, last_seen = [s.strip() for s in address_text.split(" · ", 1)]
        else:
            location_name, last_seen = address_text, None

        return OppoCloudDevice(
            device_model=device_model,
            location_name=location_name,
            last_seen=last_seen,
            is_online=is_online,
        )

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
        try:
            driver = self._get_or_create_driver()

            # Simple test - navigate to a basic page
            driver.get(CONF_OPPO_CLOUD_LOGIN_URL)
            body = WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
            )
            LOGGER.info(f"Successfully connected to Selenium Grid: {body.text[:50]}...")

        except Exception:
            # Clean up driver on connection test failure
            self._cleanup_driver()
            raise
        return True


# ruff: noqa: T201, I001, PLC0415
# Debug/testing functionality when run as module
async def _debug_main() -> None:
    """Debug main function for testing Selenium client."""
    import os
    import sys
    import logging

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Get configuration from environment variables or defaults
    username = os.getenv("OPPO_USERNAME")
    password = os.getenv("OPPO_PASSWORD")
    selenium_grid_url = os.getenv("SELENIUM_GRID_URL", "http://localhost:4444/wd/hub")

    if username is None or password is None:
        print("⚠️  Please set OPPO_USERNAME and OPPO_PASSWORD environment variables")
        print("Example:")
        print("export OPPO_USERNAME='your_oppo_account'")
        print("export OPPO_PASSWORD='your_password'")
        print("export SELENIUM_GRID_URL='http://localhost:4444/wd/hub'  # Optional")
        sys.exit(1)

    print("🔧 Testing OPPO Cloud API Client")
    print(f"   Username: {username}")
    print(f"   Selenium Grid: {selenium_grid_url}")
    print()

    client = OppoCloudApiClient(username, password, selenium_grid_url)

    try:
        # Test 1: Connection test
        print("1️⃣  Testing Selenium Grid connection...")
        connection_ok = await client.async_test_connection()
        print(f"   ✅ Connection successful: {connection_ok}")
        print()

        if connection_ok:
            # Test 2: Get device data
            print("2️⃣  Getting device data...")
            data = await client.async_get_data()
            print(f"   📱 Found {len(data)} devices:")
            for device in data:
                print(f"      - {device.device_model}")
                print(f"        Location: {device.location_name}")
                print(f"        Last seen: {device.last_seen}")
                print(f"        Online: {device.is_online}")
            print()

        print("✅ All tests completed successfully!")

    finally:
        print("\n🧹 Cleaning up...")
        await client.async_cleanup()
        print("   Cleanup completed")


if __name__ == "__main__":
    print("🚀 OPPO Cloud Tracker - Selenium API Debug Tool")
    print("=" * 50)
    asyncio.run(_debug_main())
