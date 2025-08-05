"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    JavascriptException,
)
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.client_config import ClientConfig

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.remote.webdriver import WebDriver

from custom_components.oppo_cloud_tracker.const import (
    CONF_OPPO_CLOUD_FIND_URL,
    CONF_OPPO_CLOUD_LOGIN_URL,
    LOGGER,
)
from custom_components.oppo_cloud_tracker.data import OppoCloudDevice

from .gcj2wgs import gcj2wgs


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
        self._keep_session = False

    def set_keep_selenium_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the WebDriver session (synchronous version)."""
        self._keep_session = keep_session
        # Don't cleanup in sync version to avoid blocking operations

    async def async_set_keep_selenium_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the WebDriver session between updates."""
        self._keep_session = keep_session
        # If disabling session keeping and we have an active session, clean it up
        if not keep_session and self._driver is not None:
            await self.async_cleanup()

    def _get_or_create_driver(self) -> webdriver.Remote:
        """Get existing WebDriver instance or create a new one."""
        if self._driver is not None:
            return self._driver

        try:
            # Set up Chrome options for headless mode
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument(
                "--window-size=1920,1080"
            )  # Important for headless!!
            client_config = ClientConfig(
                remote_server_addr=self._selenium_grid_url, timeout=10
            )
            self._driver = webdriver.Remote(
                command_executor=self._selenium_grid_url,
                options=chrome_options,
                client_config=client_config,
            )
        except Exception:
            self._driver = None
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
        WebDriverWait(driver, 5).until(
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
        for idx, item in enumerate(device_items):
            item.click()
            # To check device details
            device_detail_el = WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.panel-wrap > div.device-detail")
                )
            )
            devices.append(self._parse_single_device(driver, idx, device_detail_el))
            # Go back to the device list
            device_detail_el.find_element(
                By.CSS_SELECTOR,
                "div.handle-header-left > i.back",
            ).click()
        return devices

    def _parse_single_device(
        self, driver: WebDriver, idx: int, device_el: WebElement
    ) -> OppoCloudDevice:
        """Parse a single device element."""
        # Device model/name
        name_el = device_el.find_element(
            By.CSS_SELECTOR, ".device-name span:last-child"
        )
        device_model = name_el.text.strip()

        # Check is_online
        online_el = device_el.find_elements(
            By.CSS_SELECTOR, ".device-name .device-dian.online"
        )
        is_online = bool(online_el)

        # Check location_name and last_seen
        address_el = device_el.find_element(By.CSS_SELECTOR, ".device-address")
        # "XX地 · 刚刚"
        address_text = address_el.text.strip()
        if "·" in address_text:
            location_name, last_seen = [s.strip() for s in address_text.split(" · ", 1)]
        else:
            location_name, last_seen = address_text, None

        # Check battery level
        battery_el = device_el.find_elements(
            By.CSS_SELECTOR, "div.info-item.info-state > div.info-battery > div.count"
        )
        if not battery_el:
            # If no battery info, set to 0%
            battery_level = 0
            if not is_online:
                LOGGER.warning(f"OPPO Cloud {device_model} has no battery info")
        battery_text = battery_el[0].text.strip() if battery_el else ""
        battery_level = int(battery_text[:-1]) if battery_text.endswith("%") else 0
        # Check lat/lng by exec js
        gcj_lat = None
        longitude = None
        try:
            point = driver.execute_script(
                "return window.$findVm.points[arguments[0]];",
                idx,
            )
            gcj_lat = point["lat"] if point and "lat" in point else None
            gcj_lng = point["lng"] if point and "lng" in point else None
            latitude, longitude = gcj2wgs(gcj_lat, gcj_lng)
        except JavascriptException as exception:
            LOGGER.warning(f"OPPO Cloud {device_model} location not found: {exception}")

        return OppoCloudDevice(
            device_model=device_model,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            battery_level=battery_level,
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
                print(f"     - {device}")
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
