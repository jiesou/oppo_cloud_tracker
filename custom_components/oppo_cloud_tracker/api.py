"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
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


class OppoCloudApiClientSmsVerificationError(OppoCloudApiClientError):
    """
    Exception to indicate SMS verification is needed.

    Raised when OPPO Cloud requires SMS verification during login.
    The caller should prompt the user for a code and retry with sms_code=.
    """

    def __init__(self, masked_phone: str = "") -> None:
        """Initialize SMS verification error with optional masked phone."""
        self.masked_phone = masked_phone
        msg = "SMS verification required"
        if masked_phone:
            msg += f" for {masked_phone}"
        super().__init__(msg)


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
                _ = self._driver.current_url
            except WebDriverException:
                self._driver = None
            else:
                return self._driver

        url = self._remote_browser_url.strip()
        try:
            chrome_options = ChromeOptions()
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
            # Apply anti-detection via CDP before any page loads
            self._driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "Object.defineProperty(navigator,'webdriver',"
                        "{get:()=>undefined});"
                        "window.chrome={runtime:{}};"
                        "Object.defineProperty(navigator,'plugins',"
                        "{get:()=>[1,2,3,4,5]});"
                        "Object.defineProperty(navigator,'languages',"
                        "{get:()=>['en-US','en']})"
                    )
                },
            )
        except OppoCloudApiClientError:
            raise
        except Exception as exception:
            self._driver = None
            msg = f"connecting to remote browser at {url} - {exception}"
            raise OppoCloudApiClientCommunicationError(msg) from exception

        return self._driver

    def _cleanup_driver(self) -> None:
        """Clean up the WebDriver instance (sync)."""
        if not self._driver:
            return
        try:
            self._driver.quit()
        except WebDriverException:
            pass
        finally:
            self._driver = None

    async def async_cleanup(self) -> None:
        """Clean up WebDriver resources."""
        if not self._driver:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._cleanup_driver)

    async def async_auth_sms_continue(self, code: str) -> None:
        """Continue SMS auth on preserved session."""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._enter_sms_code, code
            )
        except Exception:
            await self.async_cleanup()
            raise

    async def async_login_oppo_cloud(self, sms_code: str | None = None) -> None:
        """Log in to OPPO Cloud using Selenium."""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._login_oppo_cloud, sms_code
            )
        except OppoCloudApiClientAuthenticationError:
            raise
        except OppoCloudApiClientCommunicationError:
            raise
        except OppoCloudApiClientSmsVerificationError:
            raise
        except TimeoutException as exception:
            msg = f"login - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected login - {exception}"
            raise OppoCloudApiClientError(msg) from exception

    def _complete_sms_verification(self, driver: webdriver.Remote, code: str) -> None:
        """
        Enter SMS code and click Verify inside identify iframe.

        Clicks "Get code" first (new SMS each session), enters code,
        then clicks Verify and waits for iframe to disappear.
        """
        wait = WebDriverWait(driver, 10)

        get_code_btn = wait.until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, ".uc-input-get-code-button")
            )
        )
        get_code_btn.click()

        code_input = wait.until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[type='tel'][maxlength='6']")
            )
        )
        code_input.send_keys(code)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
            code_input,
        )

        verify_btn = wait.until(
            lambda d: next(
                (
                    el
                    for el in d.find_elements(By.CSS_SELECTOR, "._verifyButton")
                    if el.is_displayed()
                    and el.get_attribute("aria-disabled") == "false"
                ),
                None,
            )
        )
        verify_btn.click()

        driver.switch_to.parent_frame()
        WebDriverWait(driver, 10).until(
            expected_conditions.invisibility_of_element_located(
                (By.CSS_SELECTOR, "iframe[name^='identify-']")
            )
        )
        LOGGER.info("OPPO Cloud SMS verification completed")

    def _enter_sms_code(self, code: str) -> None:
        """Enter SMS code and click Verify on preserved session."""
        driver = self._get_or_create_driver()
        driver.switch_to.default_content()
        login_iframe = driver.find_element(By.CSS_SELECTOR, "iframe")
        driver.switch_to.frame(login_iframe)
        verify_iframe = driver.find_element(
            By.CSS_SELECTOR, "iframe[name^='identify-']"
        )
        driver.switch_to.frame(verify_iframe)

        wait = WebDriverWait(driver, 10)

        body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
        LOGGER.info("SMS iframe body: %s", body_text)

        code_input = wait.until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[type='tel'][maxlength='6']")
            )
        )
        code_input.clear()
        code_input.send_keys(code)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
            code_input,
        )

        input_val = code_input.get_attribute("value") or ""
        body_after = driver.find_element(By.TAG_NAME, "body").text[:500]
        verify_btn = next(
            (
                el
                for el in driver.find_elements(By.CSS_SELECTOR, "._verifyButton")
                if el.is_displayed()
            ),
            None,
        )
        aria_disabled = (
            verify_btn.get_attribute("aria-disabled") if verify_btn else None
        )
        LOGGER.info(
            "SMS verify state — input='%s', aria_disabled=%s, body=%s",
            input_val,
            aria_disabled,
            body_after[:150],
        )

        if verify_btn is None or aria_disabled != "false":
            msg = (
                f"SMS Verify not ready — btn_found={verify_btn is not None}, "
                f"aria_disabled={aria_disabled}. Body: {body_after[:200]}"
            )
            raise OppoCloudApiClientAuthenticationError(msg)

        verify_btn.click()

        driver.switch_to.parent_frame()
        WebDriverWait(driver, 10).until(
            expected_conditions.invisibility_of_element_located(
                (By.CSS_SELECTOR, "iframe[name^='identify-']")
            )
        )

        driver.switch_to.default_content()
        try:
            WebDriverWait(driver, 10).until(
                expected_conditions.invisibility_of_element_located(
                    (By.CSS_SELECTOR, "iframe")
                )
            )
        except TimeoutException:
            LOGGER.warning("Login iframe still visible after SMS verification")
        LOGGER.info("OPPO Cloud SMS verification completed")

    def _login_oppo_cloud(  # noqa: PLR0915, PLR0912
        self, sms_code: str | None = None
    ) -> None:
        """Log in to OPPO Cloud using Selenium (sync)."""
        driver = self._get_or_create_driver()
        wait = WebDriverWait(driver, 10)  # default timeout

        driver.get(CONF_OPPO_CLOUD_LOGIN_URL)
        LOGGER.info("Navigated to OPPO Cloud login page")

        # Click "Sign in" button in the banner
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

            # Unified loop: handle ToS, Sign in, SMS, URL change
            # - whichever element appears first gets handled.
            # Sign in is debounced after ToS to avoid re-triggering the dialog.
            import time as _time

            deadline = _time.monotonic() + 60
            _tos_agreed_at = 0.0  # debounce sign-in click after ToS
            _sign_in_debounce = 3.0  # seconds to wait after ToS before re-click
            while _time.monotonic() < deadline:
                now = _time.monotonic()

                # 1. Handle ToS dialog if visible
                # Check for either the "Agree and continue" button or the
                # dialog mask still blocking the page during transition.
                tos_dialog_visible = False
                for dialog_el in driver.find_elements(By.CSS_SELECTOR, ".uc-dialog"):
                    try:
                        if dialog_el.is_displayed():
                            tos_dialog_visible = True
                            break
                    except StaleElementReferenceException:
                        continue
                tos_btn = None
                for el in driver.find_elements(By.CSS_SELECTOR, "[role='button']"):
                    try:
                        if el.is_displayed() and "Agree and continue" in (
                            el.text or ""
                        ):
                            tos_btn = el
                            break
                    except StaleElementReferenceException:
                        continue
                if tos_btn is not None or tos_dialog_visible:
                    if tos_btn is not None:
                        try:
                            driver.execute_script(
                                "arguments[0].focus();arguments[0].click();"
                                "arguments[0].dispatchEvent("
                                "new MouseEvent('click',"
                                "{bubbles:true,cancelable:true,view:window}))",
                                tos_btn,
                            )
                        except StaleElementReferenceException:
                            continue
                        LOGGER.info("Agreed to ToS")
                        _tos_agreed_at = now
                        # Wait for dialog to disappear
                        with contextlib.suppress(TimeoutException):
                            WebDriverWait(driver, 5).until(
                                expected_conditions.invisibility_of_element_located(
                                    (By.CSS_SELECTOR, ".uc-dialog")
                                )
                            )
                    else:
                        # Dialog visible but no agree button
                        # - could be a CAPTCHA / security verification overlay
                        body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
                        if (
                            "Security verification" in body_text
                            or "security verification" in body_text
                            or "Drag" in body_text
                            or "slide" in body_text.lower()
                        ):
                            msg = "login, CAPTCHA or security verification required"
                            raise OppoCloudApiClientAuthenticationError(msg)
                        LOGGER.debug("ToS dialog transition in progress, waiting")
                    _time.sleep(0.5)
                    continue

                # 2. Handle SMS iframe if visible
                verify_iframe = next(
                    (
                        el
                        for el in driver.find_elements(
                            By.CSS_SELECTOR, "iframe[name^='identify-']"
                        )
                        if el.is_displayed()
                    ),
                    None,
                )
                if verify_iframe is not None:
                    driver.switch_to.frame(verify_iframe)

                    if sms_code is None:
                        get_code_btn = WebDriverWait(driver, 10).until(
                            expected_conditions.element_to_be_clickable(
                                (By.CSS_SELECTOR, ".uc-input-get-code-button")
                            )
                        )
                        body_text = driver.find_element(By.TAG_NAME, "body").text
                        LOGGER.info("SMS body text: %s", body_text[:200])
                        match = re.search(r"\+86\s*\d+\**\d+", body_text)
                        masked_phone = match.group() if match else "unknown phone"
                        get_code_btn.click()
                        LOGGER.info("OPPO Cloud SMS code sent to %s", masked_phone)
                        driver.switch_to.parent_frame()
                        raise OppoCloudApiClientSmsVerificationError(masked_phone)

                    self._complete_sms_verification(driver, sms_code)
                    break

                # 3. Click enabled Sign in button (debounced after ToS)
                if now - _tos_agreed_at >= _sign_in_debounce:
                    sign_in_btn = next(
                        (
                            el
                            for el in driver.find_elements(
                                By.CSS_SELECTOR, "[role='button']"
                            )
                            if el.is_displayed()
                            and "Sign in" in (el.text or "")
                            and "uc-button-disabled"
                            not in (el.get_attribute("class") or "")
                        ),
                        None,
                    )
                    if sign_in_btn is not None:
                        with contextlib.suppress(StaleElementReferenceException):
                            sign_in_btn.click()
                        _time.sleep(1)
                        continue

                # 4. Check URL - logged in?
                try:
                    if not driver.current_url.startswith(CONF_OPPO_CLOUD_LOGIN_URL):
                        LOGGER.info("OPPO Cloud login successful")
                        return
                except WebDriverException:
                    pass

                _time.sleep(1)
            else:
                captured = driver.execute_script("return window.__capturedErrors || []")
                body = driver.find_element(By.TAG_NAME, "body").text[:300]
                clean_captured = []
                for s in captured:
                    normalized = " ".join(s.split())
                    if normalized:
                        clean_captured.append(normalized)
                if "not secure" in body:
                    clean_captured.append("Device environment not secure")
                captured_str = ", ".join(dict.fromkeys(clean_captured))
                msg = f"login, looks like {captured_str}" if captured else "login"
                raise OppoCloudApiClientAuthenticationError(msg)

        finally:
            with contextlib.suppress(WebDriverException):
                driver.switch_to.default_content()

    async def async_auth(self, sms_code: str | None = None) -> None:
        """Authenticate — preserves session on SMS verification for retry."""
        try:
            await self.async_login_oppo_cloud(sms_code)
        except OppoCloudApiClientSmsVerificationError:
            raise
        except Exception:
            await self.async_cleanup()
            raise

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
        wait = WebDriverWait(driver, 10)  # default timeout

        # Check if redirected to login page
        if not driver.current_url.startswith(CONF_OPPO_CLOUD_FIND_URL):
            msg = "not logged in or page redirected unexpectedly"
            raise OppoCloudApiClientAuthenticationError(msg)

        # Wait for the page to finish refreshing GPS locations from phones.
        # otherwise we get old, server-side cached old data

        # Step 1: Wait for the loading overlay (div.device_location) to hide
        try:
            wait.until(
                lambda d: (
                    d.find_element(
                        By.CSS_SELECTOR, "div.device_location"
                    ).value_of_css_property("display")
                    == "none"
                )
            )
        except TimeoutException:
            LOGGER.warning("device_location overlay did not hide, continuing anyway")

        # Step 2: Wait for all "正在更新"spinners to disappear
        try:
            WebDriverWait(driver, 30).until(
                lambda d: not d.find_elements(By.XPATH, "//span[text()='正在更新']")
            )
        except TimeoutException:
            LOGGER.warning("Some devices are still updating, continuing anyway")

        # Step 3: Canvas rendering of battery requires clicking each device item
        try:
            device_items = wait.until(
                expected_conditions.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#device-list .device-list ul > li")
                )
            )
            for item in device_items:
                driver.execute_script("arguments[0].click();", item)
                time.sleep(1.5)
        except Exception as exception:
            LOGGER.warning("Failed to click device item for details: %s", exception)

        # Now read the fresh data from $findVm + battery from DOM
        device_data = driver.execute_script(
            """
            if (!window.$findVm || !window.$findVm.deviceList) return null;
            var devices = JSON.parse(JSON.stringify(window.$findVm.deviceList));

            var globalBattery = null;
            var batteryEl = document.querySelector('.info-battery .count');
            if (batteryEl) {
                globalBattery = (batteryEl.innerText || batteryEl.textContent).replace('%', '').trim();
            }

            for (var i = 0; i < devices.length; i++) {
                var localBatteryEl = null;
                var liElems = document.querySelectorAll("#device-list .device-list ul > li");
                if (liElems && liElems.length > i) {
                    localBatteryEl = liElems[i].querySelector('.info-battery .count');
                }
                if (localBatteryEl) {
                    devices[i]._domBattery = (localBatteryEl.innerText || localBatteryEl.textContent).replace('%', '').trim();
                } else if (globalBattery) {
                    devices[i]._domBattery = globalBattery;
                }
            }
            return {
                deviceList: devices,
                points: window.$findVm.points || []
            };
            """
        )

        if not device_data:
            LOGGER.warning("$findVm data is unexpected")
            return []

        devices = self._parse_device_data(
            device_data["deviceList"], device_data.get("points", [])
        )

        return devices

    def _parse_device_data(
        self, devices: list[dict], points: list[dict]
    ) -> list[OppoCloudDevice]:
        """Parse a single device data."""
        result: list[OppoCloudDevice] = []

        for idx, device in enumerate(devices):
            # Device model/name
            device_model = device.get("deviceName", "Unknown Device")

            # Check is_online
            is_online = (
                device.get("onlineStatus") == 1
                or device.get("locationStatus") == "online"
            )

            # Check location_name and last_seen
            # "XX地 · 刚刚"
            poi = device.get("poi", "") or device.get("simplePoi", "")
            if "·" in poi:
                location_name, last_seen = [s.strip() for s in poi.split(" · ", 1)]
            else:
                location_name = poi.strip()
                last_seen = device.get("poiTime")

            # Check lat/lng
            latitude = None
            longitude = None

            # Method 1: get coordinates from "points"
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

            # Method 2: parse from coordinate field
            # "30.0,120.0"
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

            battery_level_raw = device.get("_domBattery") or device.get("batteryLevel") or device.get("batteryPercent")

            battery_level = None
            if battery_level_raw is not None:
                try:
                    battery_level = int(str(battery_level_raw).replace("%", "").strip())
                except (ValueError, TypeError):
                    pass

            result.append(
                OppoCloudDevice(
                    device_model=device_model,
                    location_name=location_name,
                    latitude=latitude,
                    longitude=longitude,
                    last_seen=last_seen,
                    is_online=is_online,
                    battery_level=battery_level,
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
async def _debug_main() -> None:  # noqa: PLR0915
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
    sms_code = os.getenv("OPPO_SMS_CODE")
    remote_browser_url = os.getenv("REMOTE_BROWSER_URL", "http://localhost:4444/wd/hub")

    if username is None or password is None:
        print("⚠️  Please set OPPO_USERNAME and OPPO_PASSWORD environment variables")
        print("Example:")
        print("export OPPO_USERNAME='your_oppo_account'")
        print("export OPPO_PASSWORD='your_password'")
        print("export REMOTE_BROWSER_URL='http://localhost:4444/wd/hub'  # Optional")
        sys.exit(1)

    if sms_code:
        print(f"   SMS Code: {sms_code}")

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
            # Test 2: Login
            print("    Logging in...")
            try:
                await client.async_login_oppo_cloud(sms_code=sms_code)
                print("   ✅ Login successful")
            except OppoCloudApiClientSmsVerificationError as e:
                print(f"   📱 {e}")
                print("   Set OPPO_SMS_CODE=<code> and re-run")
                return

            print()
            # Test 3: Get device data
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
