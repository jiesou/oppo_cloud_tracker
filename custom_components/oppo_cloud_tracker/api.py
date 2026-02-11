"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio
import contextlib

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.client_config import ClientConfig

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


class OppoCloudApiClientCommunicationError(OppoCloudApiClientError):
    """Exception to indicate a communication error."""

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
        remote_browser_url: str,
    ) -> None:
        """Initialize OPPO Cloud API Client."""
        self._username = username
        self._password = password
        self._remote_browser_url = remote_browser_url
        self._driver: webdriver.Remote | None = None
        self._keep_session = False

    def set_keep_browser_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session (synchronous version)."""
        self._keep_session = keep_session

    async def async_set_keep_browser_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session between updates."""
        self._keep_session = keep_session
        # If disabling session keeping and we have an active session, clean it up
        if not keep_session and self._driver is not None:
            await self.async_cleanup()

    def _get_or_create_driver(self) -> webdriver.Remote:
        """Get existing WebDriver instance or create a new one."""
        if self._driver is not None:
            try:
                # Check if driver session is still alive
                self._driver.current_url
                return self._driver
            except WebDriverException:
                self._driver = None

        url = self._remote_browser_url.strip()
        try:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")

            LOGGER.info("Connecting to Selenium Grid at %s", url)

            client_config = ClientConfig(remote_server_addr=url, timeout=30)
            self._driver = webdriver.Remote(
                command_executor=url,
                options=chrome_options,
                client_config=client_config,
            )
        except OppoCloudApiClientError:
            raise
        except Exception as exception:
            self._driver = None
            msg = f"connecting to remote browser at {url} - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception

        return self._driver

    async def async_cleanup(self) -> None:
        """Clean up WebDriver resources."""
        if not self._driver:
            return

        def _cleanup_driver() -> None:
            if not self._driver:
                return
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            finally:
                self._driver = None

        await asyncio.get_running_loop().run_in_executor(None, _cleanup_driver)

    async def async_login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Selenium."""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._login_oppo_cloud
            )
        except OppoCloudApiClientAuthenticationError:
            raise
        except OppoCloudApiClientCommunicationError:
            raise
        except TimeoutException as exception:
            msg = f"login - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected login - {exception}"
            raise OppoCloudApiClientError(msg) from exception

    def _login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Selenium (sync)."""
        driver = self._get_or_create_driver()
        wait = WebDriverWait(driver, 10)

        driver.get(CONF_OPPO_CLOUD_LOGIN_URL)
        LOGGER.info("Navigated to OPPO Cloud login page")

        # Dismiss ToS if it appears
        with contextlib.suppress(TimeoutException):
            WebDriverWait(driver, 3).until(
                expected_conditions.element_to_be_clickable(
                    (By.XPATH, "//*[normalize-space()='Agree and Close']")
                )
            ).click()
            LOGGER.debug("Dismissed ToS dialog")

        # Click "Sign in" button in the header/banner area
        wait.until(
            expected_conditions.element_to_be_clickable(
                (
                    By.XPATH,
                    "//header//*[normalize-space()='Sign in'] | "
                    "//*[@role='banner']//*[normalize-space()='Sign in']",
                )
            )
        ).click()

        # Wait for login iframe and switch to it
        login_iframe = wait.until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "iframe"))
        )
        driver.switch_to.frame(login_iframe)

        try:
            # Enter tele and password
            username_el = wait.until(
                expected_conditions.visibility_of_element_located(
                    (By.CSS_SELECTOR, "input[type='tel']")
                )
            )
            username_el.send_keys(Keys.CONTROL + "a")
            username_el.send_keys(Keys.DELETE)
            username_el.send_keys(self._username)

            password_el = wait.until(
                expected_conditions.visibility_of_element_located(
                    (By.CSS_SELECTOR, "input[type='password']")
                )
            )
            password_el.send_keys(Keys.CONTROL + "a")
            password_el.send_keys(Keys.DELETE)
            password_el.send_keys(self._password)

            # Install a passive MutationObserver to capture error messages
            observer_script = """
window.__capturedErrors = [];
const regex = /incorrect|error|fail|wrong|invalid/i;
const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
        for (const node of m.addedNodes) {
            const text = (node.textContent || '').trim();
            if (text && text.length < 500 && regex.test(text)) {
                window.__capturedErrors.push(text.substring(0, 200));
            }
        }
        if (m.type === 'characterData') {
            const text = (m.target.textContent || '').trim();
            if (text && text.length < 500 && regex.test(text)) {
                window.__capturedErrors.push(text.substring(0, 200));
            }
        }
    }
});
observer.observe(document, { childList: true, subtree: true, characterData: true });
            """
            driver.execute_script(observer_script)

            # The iframe uses custom <div role="button"> instead of native <button>,
            # and "disabled" state is a CSS class "uc-button-disabled" not an attr.
            # Wait for the visible Sign In button to lose its disabled class.
            sign_in_btn = WebDriverWait(driver, 10).until(
                lambda d: next(
                    (
                        el
                        for el in d.find_elements(By.CSS_SELECTOR, "[role='button']")
                        if el.is_displayed()
                        and "Sign in" in (el.text or "")
                        and "uc-button-disabled"
                        not in (el.get_attribute("class") or "")
                    ),
                    False,
                )
            )
            sign_in_btn.click()

            # Handle "Agree and continue" if it pops up
            with contextlib.suppress(TimeoutException):
                agree_btn = WebDriverWait(driver, 5).until(
                    lambda d: next(
                        (
                            el
                            for el in d.find_elements(
                                By.CSS_SELECTOR, "[role='button']"
                            )
                            if el.is_displayed()
                            and "Agree and continue" in (el.text or "")
                        ),
                        False,
                    )
                )
                agree_btn.click()
                LOGGER.info("Agreed to terms and conditions")

            # URL change: login success signal
            # driver.current_url always returns main page URL even inside iframe
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: not d.current_url.startswith(CONF_OPPO_CLOUD_LOGIN_URL)
                )
                LOGGER.info("OPPO Cloud login successful")
            except TimeoutException as exception:
                # Collect captured errors from iframe MutationObserver
                captured = driver.execute_script("return window.__capturedErrors || []")
                # Clean whitespace and duplicates
                clean_captured = []
                for s in captured:
                    normalized = " ".join(s.split())
                    if normalized:
                        clean_captured.append(normalized)
                captured_str = ", ".join(dict.fromkeys(clean_captured))
                msg = f"login, looks like {captured_str}" if captured else "login"
                raise OppoCloudApiClientAuthenticationError(msg) from exception
        finally:
            with contextlib.suppress(WebDriverException):
                driver.switch_to.default_content()

    async def async_get_data(self) -> list[OppoCloudDevice]:
        """Get device location data from OPPO Cloud."""
        try:
            if not self._keep_session:
                # not keeping session, must login every time
                await self.async_login_oppo_cloud()
            result = await asyncio.get_running_loop().run_in_executor(
                None, self._get_devices_data
            )
        except OppoCloudApiClientAuthenticationError:
            # Not logged in, try to log in
            LOGGER.info("OPPO Cloud not logged in, attempting to log in")
            await self.async_login_oppo_cloud()
            return await self.async_get_data()
        except TimeoutException as exception:
            msg = f"get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        finally:
            # If not keeping session, cleanup after data fetch
            if not self._keep_session:
                await self.async_cleanup()
        return result

    def _get_devices_data(self) -> list[OppoCloudDevice]:
        """Get device locations using Selenium WebDriver."""
        driver = self._get_or_create_driver()
        driver.get(CONF_OPPO_CLOUD_FIND_URL)

        # Check if redirected to login page
        if not driver.current_url.startswith(CONF_OPPO_CLOUD_FIND_URL):
            msg = "not logged in or page redirected unexpectedly"
            raise OppoCloudApiClientAuthenticationError(msg)

        # Wait for $findVm to be available with device data
        # This is more reliable than waiting for UI elements
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script(
                    "return window.$findVm && window.$findVm.deviceList "
                    "&& window.$findVm.deviceList.length > 0"
                )
            )
        except TimeoutException as exception:
            msg = "no devices, maybe session expired?"
            raise OppoCloudApiClientAuthenticationError(msg) from exception

        device_data = driver.execute_script(
            """
            if (!window.$findVm || !window.$findVm.deviceList || !window.$findVm.points)
                return null;
            return {
                deviceList: window.$findVm.deviceList,
                points: window.$findVm.points
            };
            """
        )

        if not device_data:
            LOGGER.warning("$findVm data is unexpected")
            return []

        devices = self._parse_device_data(
            device_data["deviceList"], device_data.get("points", [])
        )

        LOGGER.info("Found %d devices in OPPO Cloud", len(devices))
        return devices

    def _parse_device_data(
        self, devices: list[dict], points: list[dict]
    ) -> list[OppoCloudDevice]:
        """
        Parse device data from window.$findVm.

        Args:
            devices: List of device objects from $findVm.deviceList
            points: List of coordinate points from $findVm.points

        Returns:
            List of OppoCloudDevice objects

        """
        result: list[OppoCloudDevice] = []

        for idx, device in enumerate(devices):
            # Extract device name
            device_model = device.get("deviceName", "Unknown Device")

            # Parse POI (Point of Interest) which contains location and time
            # Format: "location · time" or just "location"
            poi = device.get("poi", "") or device.get("simplePoi", "")
            if "·" in poi:
                location_name, last_seen = [s.strip() for s in poi.split(" · ", 1)]
            else:
                location_name = poi.strip()
                last_seen = device.get("poiTime")

            # Check online status
            # onlineStatus: 1 = online, 0 = offline
            # locationStatus: "online" or other values
            is_online = (
                device.get("onlineStatus") == 1
                or device.get("locationStatus") == "online"
            )

            # Get coordinates from points array
            latitude = None
            longitude = None

            # Try to get coordinates from corresponding point
            if idx < len(points):
                point = points[idx]
                if point and "lat" in point and "lng" in point:
                    try:
                        gcj_lat = point["lat"]
                        gcj_lng = point["lng"]
                        latitude, longitude = gcj2wgs(gcj_lat, gcj_lng)
                    except (KeyError, ValueError, TypeError) as exception:
                        LOGGER.warning(
                            "Failed to convert coordinates for %s: %s",
                            device_model,
                            exception,
                        )

            # Also try to parse from coordinate field if needed
            if latitude is None and "coordinate" in device:
                try:
                    coord_str = device["coordinate"]
                    if coord_str and "," in coord_str:
                        lat_str, lng_str = coord_str.split(",", 1)
                        gcj_lat = float(lat_str)
                        gcj_lng = float(lng_str)
                        latitude, longitude = gcj2wgs(gcj_lat, gcj_lng)
                except (ValueError, AttributeError) as exception:
                    LOGGER.warning(
                        "Failed to parse coordinate field for %s: %s",
                        device_model,
                        exception,
                    )

            result.append(
                OppoCloudDevice(
                    device_model=device_model,
                    location_name=location_name,
                    latitude=latitude,
                    longitude=longitude,
                    last_seen=last_seen,
                    is_online=is_online,
                )
            )

        return result

    async def async_test_connection(self) -> bool:
        """Test connection to Selenium Grid and basic functionality."""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._test_connection
            )
        except Exception as exception:
            msg = f"Connection test failed - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception

    def _test_connection(self) -> bool:
        """Test Selenium Grid connection (sync)."""
        try:
            driver = self._get_or_create_driver()
            driver.get(CONF_OPPO_CLOUD_LOGIN_URL)
            body = WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
            )
            LOGGER.info(
                "Successfully connected to Selenium Grid: %s...", body.text[:50]
            )
        except Exception:
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
    remote_browser_url = os.getenv("REMOTE_BROWSER_URL", "http://localhost:4444/wd/hub")

    if username is None or password is None:
        print("⚠️  Please set OPPO_USERNAME and OPPO_PASSWORD environment variables")
        print("Example:")
        print("export OPPO_USERNAME='your_oppo_account'")
        print("export OPPO_PASSWORD='your_password'")
        print("export REMOTE_BROWSER_URL='http://localhost:4444/wd/hub'  # Optional")
        sys.exit(1)

    print("🔧 Testing OPPO Cloud API Client")
    print(f"   Username: {username}")
    print(f"   Remote Browser: {remote_browser_url}")
    print()

    loop = asyncio.get_running_loop()
    client = OppoCloudApiClient(username, password, remote_browser_url)

    try:
        # Test 1: Connection test
        print("    Testing Selenium Grid connection...")
        connection_ok = await client.async_test_connection()
        print(f"   ✅ Connection successful: {connection_ok}")
        print()

        if connection_ok:
            # Test 2: Get device data
            print("    Getting device data...")
            start = loop.time()
            data = await client.async_get_data()
            elapsed = loop.time() - start
            print(f"    Found {len(data)} devices:")
            for device in data:
                print(f"     - {device}")
            print(f"    Fetch time: {elapsed:.3f}s")
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
