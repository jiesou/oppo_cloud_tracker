"""OPPO Cloud Playwright API Client."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
)

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


class OppoCloudApiClientPlaywrightTimeoutError(OppoCloudApiClientError):
    """Exception to indicate a timeout error."""

    def __init__(self, context: str = "unexpected") -> None:
        """Initialize the OppoCloudApiClientPlaywrightTimeoutError with a message."""
        super().__init__(f"when {context}")


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
    """OPPO Cloud (HeyTap) API Client using Playwright."""

    def __init__(
        self,
        username: str,
        password: str,
        remote_browser_url: str,  # Keep parameter name for backward compatibility
    ) -> None:
        """Initialize OPPO Cloud API Client."""
        self._username = username
        self._password = password
        self._remote_browser_url = (
            remote_browser_url  # Actually used as browser endpoint
        )
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._keep_session = False

    def set_keep_browser_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session (synchronous version)."""
        self._keep_session = keep_session

    async def async_set_keep_browser_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session between updates."""
        self._keep_session = keep_session
        # If disabling session keeping and we have an active session, clean it up
        if not keep_session and self._browser is not None:
            await self.async_cleanup()

    async def _get_or_create_browser(self) -> Browser:
        """
        Get existing Browser instance or create a new one.

        Supports multiple remote browser connection modes:
        - ws:// or wss:// → Playwright native WebSocket connection (highest fidelity)
        - http:// with /wd/hub → Selenium Grid (via SELENIUM_REMOTE_URL env var)
        - http:// without /wd/hub → Selenium Grid (auto-detected)
        """
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        url = self._remote_browser_url.strip()
        parsed = urlparse(url)

        try:
            if parsed.scheme in ("ws", "wss"):
                # Playwright native WebSocket connection
                # e.g. ws://localhost:3000 or ws://host:3000?token=xxx
                LOGGER.info("Connecting to Playwright server at %s", url)
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect(url)

            elif parsed.scheme in ("http", "https"):
                # Selenium Grid or CDP endpoint
                selenium_url = url.rstrip("/")
                # tolerate trailing slash
                selenium_url = selenium_url.removesuffix("/wd/hub")
                # strip /wd/hub suffix for Selenium 4 compatibility

                LOGGER.info(
                    "Connecting to HTTP Remote Browser at %s (SELENIUM_REMOTE_URL=%s)",
                    url,
                    selenium_url,
                )

                # SELENIUM_REMOTE_URL must be set BEFORE async_playwright().start()
                # because Playwright Python spawns a Node.js subprocess that inherits
                # the environment at creation time. Setting os.environ after start()
                # won't propagate to the already-running Node.js process.
                os.environ["SELENIUM_REMOTE_URL"] = selenium_url

                # So restart playwright, the subprocess can picks up the env var
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None
                self._playwright = await async_playwright().start()

                self._browser = await self._playwright.chromium.launch(headless=True)

            else:
                msg = (
                    f"Unsupported browser URL scheme: {parsed.scheme}. "
                    "Use ws://, wss://, http://, or https://"
                )
                raise OppoCloudApiClientCommunicationError(msg)  # noqa: TRY301

        except OppoCloudApiClientError:
            raise
        except Exception as exception:
            self._browser = None
            msg = f"connecting to remote browser at {url} - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception

        return self._browser

    async def _get_or_create_context(self) -> BrowserContext:
        """Get existing BrowserContext or create a new one."""
        if self._context is not None:
            return self._context

        browser = await self._get_or_create_browser()
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self._context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent,
        )
        return self._context

    async def async_cleanup(self) -> None:
        """Clean up browser resources."""
        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        # Clean up Selenium env var to avoid leaking into other integrations
        os.environ.pop("SELENIUM_REMOTE_URL", None)

    async def async_login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Playwright."""
        try:
            context = await self._get_or_create_context()
            page = await context.new_page()

            try:
                await page.goto(
                    CONF_OPPO_CLOUD_LOGIN_URL, wait_until="domcontentloaded"
                )

                # Click "Sign in" button - use natural waiting
                await page.get_by_role("banner").get_by_text("Sign in").click()

                # Wait for login iframe and interact with it
                iframe_locator = page.frame_locator("iframe").first

                # Fill in credentials - Playwright auto-waits for elements
                await iframe_locator.get_by_role("textbox", name="Phone number").fill(
                    self._username
                )
                await iframe_locator.get_by_role("textbox", name="Password").fill(
                    self._password
                )

                # Click sign in button - Playwright waits for it to be enabled
                await iframe_locator.get_by_role("button", name="Sign in").click()

                # Handle "Terms and conditions" dialog if it appears
                agree_button = iframe_locator.get_by_role(
                    "button", name="Agree and continue"
                )
                try:
                    await agree_button.click(timeout=5000)
                    LOGGER.info("Agreed to terms and conditions")
                except PlaywrightTimeoutError:
                    # Dialog might not appear if already agreed before
                    LOGGER.debug("Terms and conditions dialog did not appear")

                # Wait for successful login - URL change indicates success
                try:
                    await page.wait_for_url(
                        lambda url: (not url.startswith(CONF_OPPO_CLOUD_LOGIN_URL)),
                        timeout=10000,
                    )
                    LOGGER.info("OPPO Cloud login successful")
                except PlaywrightTimeoutError as exception:
                    # Try to detect error messages in iframe
                    current_url = page.url
                    LOGGER.error(f"Login timeout, current URL: {current_url}")

                    try:
                        error_messages = await iframe_locator.locator(
                            "text=/error|错误|失败/i"
                        ).all_text_contents()
                        if error_messages:
                            LOGGER.error(f"Login error messages: {error_messages}")
                    except PlaywrightTimeoutError:
                        pass

                    msg = "login"
                    raise OppoCloudApiClientAuthenticationError(msg) from exception
            finally:
                await page.close()

        except PlaywrightTimeoutError as exception:
            msg = f"login - {exception}"
            raise OppoCloudApiClientPlaywrightTimeoutError(msg) from exception
        except OppoCloudApiClientAuthenticationError:
            raise
        except Exception as exception:
            msg = f"Unexpected login - {exception}"
            raise OppoCloudApiClientError(msg) from exception

    async def async_get_data(self) -> list[OppoCloudDevice]:
        """Get device location data from OPPO Cloud."""
        try:
            result = await self._get_devices_data()
        except OppoCloudApiClientAuthenticationError:
            # Not logged in, try to log in
            LOGGER.info("OPPO Cloud not logged in, attempting to log in")
            await self.async_login_oppo_cloud()
            return await self.async_get_data()
        except PlaywrightTimeoutError as exception:
            msg = f"get_devices_data - {exception}"
            raise OppoCloudApiClientPlaywrightTimeoutError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        finally:
            # If not keeping session, cleanup after successful data fetch
            if not self._keep_session:
                await self.async_cleanup()
        return result

    async def _get_devices_data(self) -> list[OppoCloudDevice]:
        """Get device locations using Playwright."""
        context = await self._get_or_create_context()
        page = await context.new_page()

        try:
            await page.goto(CONF_OPPO_CLOUD_FIND_URL, wait_until="domcontentloaded")

            # Check if redirected to login page
            if not page.url.startswith(CONF_OPPO_CLOUD_FIND_URL):
                msg = "not logged in or page redirected unexpectedly"
                raise OppoCloudApiClientAuthenticationError(msg)

            # Wait for $findVm to be available with device data
            # This is more reliable than waiting for UI elements
            try:
                await page.wait_for_function(
                    (
                        "window.$findVm && window.$findVm.deviceList && "
                        "window.$findVm.deviceList.length > 0"
                    ),
                    timeout=30000,
                )
            except PlaywrightTimeoutError as exception:
                # Check if there are actually no devices
                has_find_vm = await page.evaluate("window.$findVm !== undefined")
                if has_find_vm:
                    device_list = await page.evaluate("window.$findVm.deviceList || []")
                    if len(device_list) == 0:
                        LOGGER.info("No devices found in OPPO Cloud")
                        return []
                # If $findVm is not available, might not be logged in
                msg = "not logged in or session expired"
                raise OppoCloudApiClientAuthenticationError(msg) from exception

            # Extract all device data directly from JavaScript
            device_data = await page.evaluate(
                """
                () => {
                    if (!window.$findVm || !window.$findVm.deviceList) return null;

                    return {
                        deviceList: window.$findVm.deviceList,
                        points: window.$findVm.points
                    };
                }
                """
            )

            if not device_data or not device_data.get("deviceList"):
                LOGGER.warning("No device data available from $findVm")
                return []

            devices = self._parse_device_data(
                device_data["deviceList"], device_data.get("points", [])
            )

            LOGGER.info(f"Found {len(devices)} devices in OPPO Cloud")
            return devices
        finally:
            await page.close()

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
                            f"Failed to convert coordinates for "
                            f"{device_model}: {exception}"
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
                        f"Failed to parse coordinate field for "
                        f"{device_model}: {exception}"
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
        """
        Test connection to browser endpoint and basic functionality.

        Returns:
            True if connection is successful

        """
        try:
            context = await self._get_or_create_context()
            page = await context.new_page()

            try:
                # Simple test - navigate to a basic page
                await page.goto(
                    CONF_OPPO_CLOUD_LOGIN_URL, wait_until="domcontentloaded"
                )
                body_text = await page.locator("body").text_content()
                LOGGER.info(
                    f"Successfully connected to browser: {(body_text or '')[:50]}..."
                )
                return True
            finally:
                await page.close()

        except PlaywrightTimeoutError as exception:
            await self.async_cleanup()
            msg = f"Connection test failed - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception


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

    client = OppoCloudApiClient(username, password, remote_browser_url)

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
    print("🚀 OPPO Cloud Tracker - Playwright API Debug Tool")
    print("=" * 50)
    asyncio.run(_debug_main())
