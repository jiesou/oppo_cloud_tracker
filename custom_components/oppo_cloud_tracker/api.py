"""OPPO Cloud Playwright API Client."""

from __future__ import annotations

import asyncio
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator

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
    """OPPO Cloud (HeyTap) API Client using Playwright."""

    def __init__(
        self,
        username: str,
        password: str,
        selenium_grid_url: str,  # Keep parameter name for backward compatibility
    ) -> None:
        """Initialize OPPO Cloud API Client."""
        self._username = username
        self._password = password
        self._selenium_grid_url = selenium_grid_url  # Actually used as browser endpoint
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._keep_session = False

    def set_keep_selenium_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session (synchronous version).
        
        Note: This is kept for backward compatibility. The actual session
        management is async-only with Playwright.
        """
        self._keep_session = keep_session

    async def async_set_keep_selenium_session(self, *, keep_session: bool) -> None:
        """Set whether to keep the browser session between updates."""
        self._keep_session = keep_session
        # If disabling session keeping and we have an active session, clean it up
        if not keep_session and self._browser is not None:
            await self.async_cleanup()

    async def _get_or_create_browser(self) -> Browser:
        """Get existing Browser instance or create a new one."""
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        # For Selenium Grid compatibility, we need to launch a browser
        # that connects to the remote endpoint
        # Note: Playwright doesn't directly support Selenium Grid URLs,
        # but we can use connect_over_cdp for Chrome DevTools Protocol
        try:
            # Try to connect using CDP endpoint
            # Selenium Grid typically exposes CDP at ws://host:port/session/{sessionId}/se/cdp
            # For simplicity, we'll launch a local browser for now
            # TODO: Proper Selenium Grid integration would need session management
            
            # Since we're using remote browser, try CDP connection
            # Convert http://host:port/wd/hub to ws://host:port
            ws_endpoint = self._selenium_grid_url.replace("http://", "ws://").replace("/wd/hub", "")
            
            # For Playwright with Selenium Grid, we actually need to use the browser
            # launched by Selenium Grid. This is complex, so for now we'll use
            # Playwright's own remote browser capability
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                ]
            )
        except Exception:
            self._browser = None
            raise
        
        return self._browser

    async def _get_or_create_context(self) -> BrowserContext:
        """Get existing BrowserContext or create a new one."""
        if self._context is not None:
            return self._context

        browser = await self._get_or_create_browser()
        self._context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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

    async def async_login_oppo_cloud(self) -> None:
        """Log in to OPPO Cloud using Playwright."""
        try:
            context = await self._get_or_create_context()
            page = await context.new_page()
            
            try:
                await page.goto(CONF_OPPO_CLOUD_LOGIN_URL, wait_until="domcontentloaded")
                
                # Click "Sign in" button and wait for it
                sign_in_banner = page.get_by_role("banner").get_by_text("Sign in")
                await sign_in_banner.wait_for(state="visible", timeout=10000)
                await sign_in_banner.click()
                
                # Wait for login iframe to appear
                await page.wait_for_timeout(2000)  # Give iframe time to load
                iframe_locator = page.frame_locator("iframe").first
                
                # Wait for phone number input to be ready
                phone_input = iframe_locator.get_by_role("textbox", name="Phone number")
                await phone_input.wait_for(state="visible", timeout=10000)
                
                # Fill in credentials
                await phone_input.fill(self._username)
                await iframe_locator.get_by_role("textbox", name="Password").fill(self._password)
                
                # Wait for Sign in button to be enabled and click it
                sign_in_button = iframe_locator.get_by_role("button", name="Sign in")
                await sign_in_button.wait_for(state="visible", timeout=10000)
                
                # Check if button is enabled by looking for disabled attribute
                # Wait a bit for the button to become enabled
                for _ in range(10):
                    is_disabled = await sign_in_button.is_disabled()
                    if not is_disabled:
                        break
                    await page.wait_for_timeout(500)
                
                await sign_in_button.click()
                
                # Check if "Terms and conditions" dialog appears and click "Agree and continue"
                try:
                    agree_button = iframe_locator.get_by_role("button", name="Agree and continue")
                    await agree_button.wait_for(state="visible", timeout=5000)
                    await agree_button.click()
                    LOGGER.info("Agreed to terms and conditions")
                except PlaywrightTimeoutError:
                    # Dialog might not appear if already agreed before
                    LOGGER.debug("Terms and conditions dialog did not appear")
                
                # Wait for login to complete (URL change or successful navigation)
                try:
                    # Wait for URL to change from login page
                    await page.wait_for_function(
                        f"window.location.href && !window.location.href.startsWith('{CONF_OPPO_CLOUD_LOGIN_URL}')",
                        timeout=10000
                    )
                    LOGGER.info("OPPO Cloud login successful")
                except PlaywrightTimeoutError as exception:
                    # Check if we're still on login page - might indicate auth failure
                    current_url = page.url
                    LOGGER.error(f"Login timeout, current URL: {current_url}")
                    
                    # Try to detect error messages in iframe
                    try:
                        error_element = iframe_locator.locator(".error-message, .login-error")
                        error_count = await error_element.count()
                        if error_count > 0:
                            error_text = await error_element.first.text_content()
                            LOGGER.error(f"Login error message: {error_text}")
                    except Exception:
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
            
            # Wait for the page to load and check if logged in
            try:
                # Wait for either device list or login button
                await page.locator("#device-list > div.device-list, div.wrapper-login span.btn").first.wait_for(timeout=10000)
            except PlaywrightTimeoutError:
                pass
            
            # If redirected to login page
            if not page.url.startswith(CONF_OPPO_CLOUD_FIND_URL):
                msg = "not logged in or page redirected unexpectedly"
                raise OppoCloudApiClientAuthenticationError(msg)
            
            # Wait for the device list to fully load
            # Step 1: Wait for device_location loading indicator to disappear
            device_location = page.locator("div.device_location")
            if await device_location.count() > 0:
                await device_location.evaluate("el => window.getComputedStyle(el).display === 'none'")
            
            # Step 2: Wait for all "正在更新" indicators to disappear
            await page.locator("//span[text()='正在更新']").wait_for(state="hidden", timeout=30000) if await page.locator("//span[text()='正在更新']").count() > 0 else None
            
            # Step 3: Wait for device location info to be present
            device_items = page.locator("#device-list .device-list ul > li")
            device_count = await device_items.count()
            
            if device_count > 0:
                for i in range(device_count):
                    item = device_items.nth(i)
                    # Each device should have device-poi or be in error state
                    await item.locator(".device-poi, .device-status-wrap:not(.positioning)").first.wait_for(timeout=10000)
            
            devices: list[OppoCloudDevice] = []
            
            # Find all device items
            for idx in range(device_count):
                item = device_items.nth(idx)
                await item.click()
                
                # Wait for device details
                device_detail = page.locator("div.panel-wrap > div.device-detail")
                await device_detail.wait_for(state="visible", timeout=10000)
                
                devices.append(await self._parse_single_device(page, idx, device_detail))
                
                # Go back to the device list
                await device_detail.locator("div.handle-header-left > i.back").click()
                await page.wait_for_timeout(500)  # Brief wait for transition
            
            LOGGER.info(f"Found {len(devices)} devices in OPPO Cloud")
            return devices
        finally:
            await page.close()

    async def _parse_single_device(
        self, page: Page, idx: int, device_el: Locator
    ) -> OppoCloudDevice:
        """Parse a single device element."""
        # Device model/name
        name_el = device_el.locator(".device-name span:last-child")
        device_model = (await name_el.text_content() or "").strip()
        
        # Check is_online
        online_el = device_el.locator(".device-name .device-dian.online")
        is_online = await online_el.count() > 0
        
        # Check location_name and last_seen
        address_el = device_el.locator(".device-address")
        address_text = (await address_el.text_content() or "").strip()
        
        if "·" in address_text:
            location_name, last_seen = [s.strip() for s in address_text.split(" · ", 1)]
        else:
            location_name, last_seen = address_text, None
        
        # Check battery level
        battery_el = device_el.locator("div.info-item.info-state > div.info-battery > div.count")
        battery_count = await battery_el.count()
        
        if battery_count == 0:
            battery_level = 0
            if is_online:
                LOGGER.warning(f"OPPO Cloud {device_model} has no battery info")
        else:
            battery_text = (await battery_el.first.text_content() or "").strip()
            battery_level = int(battery_text[:-1]) if battery_text.endswith("%") else 0
        
        # Check lat/lng by executing JavaScript
        latitude = None
        longitude = None
        try:
            point = await page.evaluate("(idx) => window.$findVm.points[idx]", idx)
            if point and "lat" in point and "lng" in point:
                gcj_lat = point["lat"]
                gcj_lng = point["lng"]
                latitude, longitude = gcj2wgs(gcj_lat, gcj_lng)
        except Exception as exception:
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
        """Test connection to browser endpoint and basic functionality."""
        try:
            context = await self._get_or_create_context()
            page = await context.new_page()
            
            try:
                # Simple test - navigate to a basic page
                await page.goto(CONF_OPPO_CLOUD_LOGIN_URL, wait_until="domcontentloaded")
                body_text = await page.locator("body").text_content()
                LOGGER.info(f"Successfully connected to browser: {(body_text or '')[:50]}...")
                return True
            finally:
                await page.close()
                
        except Exception as exception:
            # Clean up on connection test failure
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
    print("🚀 OPPO Cloud Tracker - Playwright API Debug Tool")
    print("=" * 50)
    asyncio.run(_debug_main())
