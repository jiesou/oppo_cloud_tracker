"""OPPO Cloud Selenium API Client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time

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
    LOGIN_RETRY_ATTEMPTS,
    LOGIN_RETRY_BACKOFF,
    LOGGER,
    MANUAL_VERIFY_TIMEOUT,
    SESSION_MAX_AGE,
    VERIFICATION_POLL_INTERVAL,
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


class OppoCloudApiClientVerificationRequiredError(OppoCloudApiClientError):
    """
    Exception for an interactive graphic security verification (e.g. slider).

    The HeyTap login may present a drag-slider / puzzle CAPTCHA that only a
    human can complete. This is NOT auto-solved. The browser session is kept
    alive so the user can finish the drag manually through the Selenium Grid
    noVNC view (see ``novnc_url``), then the client resumes automatically.

    Carries enough context for a clear error state:
      - verification_type: "slider" / "security" / ...
      - evidence: detection hits (DOM selector / text keyword), for logs
      - novnc_url: where a human can complete the verification
      - screenshot_path: last captured page screenshot (may be None)
    """

    def __init__(
        self,
        verification_type: str = "security",
        *,
        evidence: list[str] | None = None,
        novnc_url: str = "",
        screenshot_path: str | None = None,
        detail: str = "",
    ) -> None:
        """Initialize the verification-required error with context."""
        self.verification_type = verification_type
        self.evidence = evidence or []
        self.novnc_url = novnc_url
        self.screenshot_path = screenshot_path
        msg = f"login, {verification_type} verification required (manual step)"
        if detail:
            msg += f": {detail}"
        if novnc_url:
            msg += f" — complete it in {novnc_url}"
        super().__init__(msg)


def _element_probe(el) -> tuple[bool, str, str]:
    """Return (is_displayed, text, class) for a found element, safely.

    The OPPO login page (Vue) re-renders aggressively: an element returned
    by find_elements() may already be detached by the time it is inspected.
    ChromeDriver reports that as NoSuchElementException ("no such element:
    element not found") or "Node with given id does not belong to the
    document" — not only as StaleElementReferenceException — so swallow
    any WebDriverException and treat the element as gone.
    """
    try:
        return el.is_displayed(), el.text or "", el.get_attribute("class") or ""
    except WebDriverException:
        return False, "", ""


def _body_text(driver: webdriver.Remote, limit: int = 500) -> str:
    """Read <body> innerText, tolerating documents that are mid-navigation."""
    try:
        return driver.find_element(By.TAG_NAME, "body").text[:limit]
    except WebDriverException:
        return ""


def _detect_verification(driver: webdriver.Remote) -> tuple[str, list[str]] | None:
    """Detect an interactive security-verification widget on the page.

    Scans the CURRENT frame (call it after switching into the right iframe)
    for slider/graphic-captcha fingerprints: known DOM selectors of common
    behavior-captcha widgets and the text the HeyTap verify dialog shows.

    Returns (verification_type, evidence) or None. Detection only — this
    never attempts to solve the challenge; the caller hands it to a human.
    """
    from .const import (
        VERIFY_DOM_SELECTORS,
        VERIFY_TEXT_SECURITY,
        VERIFY_TEXT_SLIDER,
    )

    evidence: list[str] = []

    for selector in VERIFY_DOM_SELECTORS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
        except WebDriverException:
            continue
        if any(_element_probe(el)[0] for el in els):
            evidence.append(f"dom:{selector}")

    body = _body_text(driver, 1200)
    body_lower = body.lower()
    slider_hits = [kw for kw in VERIFY_TEXT_SLIDER if kw.lower() in body_lower]
    security_hits = [kw for kw in VERIFY_TEXT_SECURITY if kw.lower() in body_lower]
    if slider_hits:
        evidence.append(f"text-slider:{','.join(slider_hits[:5])}")
    if security_hits:
        evidence.append(f"text-security:{','.join(security_hits[:5])}")

    if not evidence:
        return None
    # Slider keywords or slider DOM => drag verification; else generic security.
    if slider_hits or any(e.startswith("dom:") for e in evidence):
        return "slider", evidence
    return "security", evidence


class OppoCloudApiClient:
    """OPPO Cloud (HeyTap) API Client using Selenium."""

    def __init__(
        self,
        username: str,
        password: str,
        remote_browser_url: str,
        session_store_path: str | None = None,
        novnc_url: str | None = None,
    ) -> None:
        """Initialize OPPO Cloud API Client.

        session_store_path: optional JSON file used to persist browser
            cookies so a verified login session can be REUSED across
            restarts instead of re-triggering the security verification.
        novnc_url: optional URL of the Selenium Grid noVNC view, shown in
            error/log messages so a human can open it and complete the
            interactive verification manually.
        """
        self._username = username
        self._password = password
        self._remote_browser_url = remote_browser_url
        self._session_store_path = session_store_path
        self._novnc_url = novnc_url or self._derive_novnc_url(remote_browser_url)
        self._driver: webdriver.Remote | None = None
        self._keep_session = False
        self._verification_pending = False
        self._verification_deadline = 0.0

    @staticmethod
    def _derive_novnc_url(remote_browser_url: str) -> str:
        """Best-effort noVNC URL from a Selenium Grid URL (host:7900 convention)."""
        import re as _re

        match = _re.search(r"^(https?://[^/:]+)(?::(\d+))?", remote_browser_url.strip())
        if not match:
            return ""
        host = match.group(1)
        return f"{host}:7900"

    def _load_persisted_cookies(self) -> list[dict]:
        """Load cookies saved from a previous verified session, if any."""
        if not self._session_store_path or not os.path.isfile(self._session_store_path):
            return []
        try:
            with open(self._session_store_path, encoding="utf-8") as handle:
                data = json.load(handle)
            cookies = data.get("cookies", [])
            saved_at = data.get("saved_at", 0)
            if time.time() - saved_at > SESSION_MAX_AGE:
                LOGGER.info("Persisted OPPO session is older than %ds, ignoring", SESSION_MAX_AGE)
                return []
            LOGGER.info("Loaded %d persisted session cookies", len(cookies))
            return cookies
        except (OSError, ValueError) as exception:
            LOGGER.warning("Failed to read session store: %s", exception)
            return []

    def _persist_cookies(self, driver: webdriver.Remote) -> None:
        """Save ALL browser cookies (cross-domain) for session reuse.

        Plain ``get_cookies()`` only returns cookies of the current page's
        domain — the id.oppo.com SSO cookies would be lost, and a restored
        session would silently fail later. CDP ``Network.getAllCookies``
        captures every cookie in the jar instead.
        """
        if not self._session_store_path:
            return
        try:
            try:
                payload = driver.execute_cdp_cmd("Network.getAllCookies", {})
                cookies = payload.get("cookies", [])
            except WebDriverException:
                cookies = driver.get_cookies()
            os.makedirs(os.path.dirname(self._session_store_path) or ".", exist_ok=True)
            with open(self._session_store_path, "w", encoding="utf-8") as handle:
                json.dump({"saved_at": time.time(), "cookies": cookies}, handle)
            domains = sorted({c.get("domain", "?") for c in cookies})
            LOGGER.info(
                "Persisted %d session cookies (domains: %s)", len(cookies), domains
            )
        except (OSError, WebDriverException) as exception:
            LOGGER.warning("Failed to persist session cookies: %s", exception)

    def _capture_screenshot(self, driver: webdriver.Remote, tag: str) -> str | None:
        """Save a PNG screenshot for diagnostics; return its path or None."""
        if not self._session_store_path:
            return None
        try:
            directory = os.path.dirname(self._session_store_path) or "."
            path = os.path.join(directory, f"{tag}_{int(time.time())}.png")
            driver.save_screenshot(path)
            LOGGER.info("Saved verification screenshot: %s", path)
            return path
        except (OSError, WebDriverException) as exception:
            LOGGER.debug("Screenshot capture failed: %s", exception)
            return None

    def _try_restore_session(self, driver: webdriver.Remote) -> bool:
        """Restore persisted cookies; True only when the session REALLY works.

        The OPPO SPA redirects to the login page asynchronously, so checking
        the URL right after navigation is a false positive — a dead session
        still looks valid for a moment. Only ``window.$findVm`` appearing
        proves the authenticated find app actually booted.
        """
        cookies = self._load_persisted_cookies()
        if not cookies:
            return False
        try:
            # A page on the target domain must be open before cookies can be set.
            driver.get(CONF_OPPO_CLOUD_LOGIN_URL)
            restored = 0
            for cookie in cookies:
                cookie = {
                    key: value
                    for key, value in cookie.items()
                    if key
                    in (
                        "name",
                        "value",
                        "path",
                        "domain",
                        "secure",
                        "httpOnly",
                        "expiry",
                        "sameSite",
                    )
                }
                try:
                    driver.add_cookie(cookie)
                except WebDriverException:
                    continue
                restored += 1
            LOGGER.info("Restored %d/%d persisted session cookies", restored, len(cookies))
            driver.get(CONF_OPPO_CLOUD_FIND_URL)
            # Wait for the SPA to settle: either the find app boots ($findVm)
            # or the page bounces to the login screen.
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return !!window.$findVm")
                    or "login" in (d.current_url or "")
                )
            except TimeoutException:
                pass
            if driver.execute_script("return !!window.$findVm"):
                LOGGER.info("Persisted OPPO session still valid — login skipped")
                return True
            LOGGER.info(
                "Persisted OPPO session expired (now at %s)", driver.current_url
            )
        except WebDriverException as exception:
            LOGGER.warning("Session restore failed: %s", exception)
        return False

    def _scan_for_verification(
        self, driver: webdriver.Remote, restore_frame=None
    ) -> tuple[str, list[str]] | None:
        """Scan page and nested iframes for an interactive verification widget.

        Always scans from the default content frame so element references
        never go stale across frame switches. SMS-style verify iframes are
        skipped so the SMS flow keeps working. When ``restore_frame`` is
        given (the login iframe element), the driver is switched back into
        it afterwards so callers can keep using their frame context.
        """
        try:
            driver.switch_to.default_content()
            hit = _detect_verification(driver)
            if hit:
                return hit

            for outer in driver.find_elements(By.CSS_SELECTOR, "iframe"):
                if not _element_probe(outer)[0]:
                    continue
                try:
                    driver.switch_to.frame(outer)
                except WebDriverException:
                    continue
                try:
                    hit = _detect_verification(driver)
                    if hit:
                        return hit
                    # Nested verify iframe: only treat as graphic verification
                    # when it is NOT the SMS-code form.
                    for inner in driver.find_elements(
                        By.CSS_SELECTOR, "iframe[name^='identify-']"
                    ):
                        if not _element_probe(inner)[0]:
                            continue
                        try:
                            driver.switch_to.frame(inner)
                        except WebDriverException:
                            continue
                        try:
                            has_sms_ui = any(
                                _element_probe(el)[0]
                                for el in driver.find_elements(
                                    By.CSS_SELECTOR,
                                    ".uc-input-get-code-button, input[type='tel'][maxlength='6']",
                                )
                            )
                            if has_sms_ui:
                                continue
                            hit = _detect_verification(driver)
                            if hit:
                                return hit
                        finally:
                            driver.switch_to.default_content()
                            try:
                                driver.switch_to.frame(outer)
                            except WebDriverException:
                                pass
                finally:
                    driver.switch_to.default_content()
            return None
        finally:
            if restore_frame is not None:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(restore_frame)
                except WebDriverException:
                    pass

    def _raise_verification_required(
        self, driver: webdriver.Remote, kind: tuple[str, list[str]]
    ) -> None:
        """Log context and raise a manual-verification-required error."""
        verification_type, evidence = kind
        screenshot_path = self._capture_screenshot(driver, "verification_required")
        body = ""
        try:
            driver.switch_to.default_content()
            body = _body_text(driver, 200)
        except WebDriverException:
            pass
        LOGGER.warning(
            "OPPO Cloud requires manual %s verification (evidence: %s). "
            "Complete it via the browser view at %s. body=%s",
            verification_type,
            ", ".join(evidence),
            self._novnc_url or "(noVNC URL unknown)",
            body,
        )
        if not self._verification_pending:
            # First detection: open the manual-verification window now.
            # Re-detections (polling) must NOT extend the deadline.
            self._verification_pending = True
            self._verification_deadline = time.monotonic() + MANUAL_VERIFY_TIMEOUT
        raise OppoCloudApiClientVerificationRequiredError(
            verification_type,
            evidence=evidence,
            novnc_url=self._novnc_url,
            screenshot_path=screenshot_path,
            detail="manual completion required",
        )

    def _wait_for_manual_verification(self, timeout: float) -> None:
        """Poll the preserved session until a human completes the verification.

        Returns silently once the login page is left behind (login completed).
        Raises VerificationRequiredError on timeout with a clear message.
        """
        driver = self._get_or_create_driver()
        deadline = time.monotonic() + timeout
        last_state = ""
        while time.monotonic() < deadline:
            try:
                url = driver.current_url
            except WebDriverException:
                url = ""
            if url and not url.startswith(CONF_OPPO_CLOUD_LOGIN_URL):
                LOGGER.info("Manual verification completed (now at %s)", url)
                self._verification_pending = False
                self._verification_deadline = 0.0
                self._persist_cookies(driver)
                return
            try:
                kind = self._scan_for_verification(driver)
                state = f"{kind[0]}:{kind[1]}" if kind else "waiting"
            except WebDriverException as exception:
                kind = ("error", [str(exception)])
                state = f"scan-error:{exception}"
            if kind is None:
                # Challenge cleared but login may still need a Sign in click
                # to proceed — mirror the main login loop's step 3.
                try:
                    driver.switch_to.default_content()
                    login_iframe = next(
                        (
                            el
                            for el in driver.find_elements(By.CSS_SELECTOR, "iframe")
                            if _element_probe(el)[0]
                        ),
                        None,
                    )
                    if login_iframe is not None:
                        driver.switch_to.frame(login_iframe)
                    for el in driver.find_elements(By.CSS_SELECTOR, "[role='button']"):
                        displayed, text, cls = _element_probe(el)
                        if (
                            displayed
                            and "Sign in" in text
                            and "uc-button-disabled" not in cls
                        ):
                            el.click()
                            LOGGER.info("Re-clicked Sign in after manual verification")
                            break
                except WebDriverException:
                    pass
            if state != last_state:
                LOGGER.info("Waiting for manual verification... %s", state)
                last_state = state
            time.sleep(VERIFICATION_POLL_INTERVAL)
        screenshot_path = self._capture_screenshot(driver, "verification_timeout")
        msg = f"manual verification not completed within {timeout:.0f}s"
        raise OppoCloudApiClientVerificationRequiredError(
            "slider",
            evidence=["timeout"],
            novnc_url=self._novnc_url,
            screenshot_path=screenshot_path,
            detail=msg,
        )

    async def async_wait_for_manual_verification(
        self, timeout: float = MANUAL_VERIFY_TIMEOUT
    ) -> None:
        """Async wrapper: wait for the human to finish the verification."""
        await asyncio.get_running_loop().run_in_executor(
            None, self._wait_for_manual_verification, timeout
        )

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
        """Log in to OPPO Cloud using Selenium.

        Transient failures (DOM races, page-load hiccups) are retried on a
        fresh browser session; auth/CAPTCHA/SMS outcomes are not.
        """
        max_attempts = LOGIN_RETRY_ATTEMPTS
        last_error: OppoCloudApiClientError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._login_oppo_cloud, sms_code
                )
                return
            except (
                OppoCloudApiClientAuthenticationError,
                OppoCloudApiClientCommunicationError,
                OppoCloudApiClientSmsVerificationError,
                OppoCloudApiClientVerificationRequiredError,
            ):
                raise
            except TimeoutException as exception:
                last_error = OppoCloudApiClientError(f"login - {exception}")
            except Exception as exception:
                last_error = OppoCloudApiClientError(f"Unexpected login - {exception}")
            if attempt < max_attempts:
                LOGGER.warning(
                    "Login attempt %d/%d failed: %s — retrying with a fresh session",
                    attempt,
                    max_attempts,
                    last_error,
                )
                # Drop the flaky driver so the retry starts clean.
                await self.async_cleanup()
                await asyncio.sleep(LOGIN_RETRY_BACKOFF)
        raise last_error if last_error else OppoCloudApiClientError("login")

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

        def _verify_ready(el) -> bool:
            try:
                return el.is_displayed() and el.get_attribute("aria-disabled") == "false"
            except WebDriverException:
                return False

        verify_btn = wait.until(
            lambda d: next(
                (
                    el
                    for el in d.find_elements(By.CSS_SELECTOR, "._verifyButton")
                    if _verify_ready(el)
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
        try:
            login_iframe = driver.find_element(By.CSS_SELECTOR, "iframe")
            driver.switch_to.frame(login_iframe)
            verify_iframe = driver.find_element(
                By.CSS_SELECTOR, "iframe[name^='identify-']"
            )
            driver.switch_to.frame(verify_iframe)
        except WebDriverException as exception:
            raise OppoCloudApiClientAuthenticationError(
                "SMS verification iframe is gone (session expired) — retry login"
            ) from exception

        wait = WebDriverWait(driver, 10)

        body_text = _body_text(driver)
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
        body_after = _body_text(driver)
        verify_btn = next(
            (
                el
                for el in driver.find_elements(By.CSS_SELECTOR, "._verifyButton")
                if _element_probe(el)[0]
            ),
            None,
        )
        try:
            aria_disabled = (
                verify_btn.get_attribute("aria-disabled") if verify_btn else None
            )
        except WebDriverException:
            verify_btn = None
            aria_disabled = None
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

        # A previous login attempt may be waiting for the human to finish an
        # interactive verification. Never navigate away in that case — doing
        # so would discard the user's progress on the slider.
        if self._verification_pending and time.monotonic() < self._verification_deadline:
            try:
                current_url = driver.current_url
            except WebDriverException:
                current_url = ""
            if current_url and not current_url.startswith(CONF_OPPO_CLOUD_LOGIN_URL):
                LOGGER.info("Manual verification already completed (at %s)", current_url)
                self._verification_pending = False
                self._verification_deadline = 0.0
                self._persist_cookies(driver)
                return
            # Still waiting for the human: surface the same clear error state.
            kind = ("slider", ["manual-verification-pending"])
            self._raise_verification_required(driver, kind)
        if self._verification_pending:
            # Deadline passed — give up on the stale attempt and start fresh.
            LOGGER.info("Previous manual verification window expired, restarting login")
            self._verification_pending = False
            self._verification_deadline = 0.0

        # Reuse a previously verified session when possible — avoids
        # re-triggering the interactive security verification entirely.
        if sms_code is None and self._try_restore_session(driver):
            return

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
                    if _element_probe(dialog_el)[0]:
                        tos_dialog_visible = True
                        break
                tos_btn = None
                for el in driver.find_elements(By.CSS_SELECTOR, "[role='button']"):
                    displayed, text, _cls = _element_probe(el)
                    if displayed and "Agree and continue" in text:
                        tos_btn = el
                        break
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
                        except WebDriverException:
                            # Node detached mid-click (page re-rendered) —
                            # just rescan on the next loop iteration.
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
                        # Dialog visible but no agree button — could be a
                        # graphic security verification overlay (slider etc.).
                        # Do a structured scan (DOM fingerprints + text) and
                        # hand the challenge to a human instead of guessing.
                        kind = self._scan_for_verification(
                            driver, restore_frame=login_iframe
                        )
                        if kind is not None:
                            self._raise_verification_required(driver, kind)
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
                        if _element_probe(el)[0]
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
                        body_text = _body_text(driver)
                        LOGGER.info("SMS body text: %s", body_text[:200])
                        match = re.search(r"\+86\s*\d+\**\d+", body_text)
                        masked_phone = match.group() if match else "unknown phone"
                        get_code_btn.click()
                        LOGGER.info("OPPO Cloud SMS code sent to %s", masked_phone)
                        driver.switch_to.parent_frame()
                        raise OppoCloudApiClientSmsVerificationError(masked_phone)

                    self._complete_sms_verification(driver, sms_code)
                    self._persist_cookies(driver)
                    break

                # 3. Click enabled Sign in button (debounced after ToS)
                if now - _tos_agreed_at >= _sign_in_debounce:
                    sign_in_btn = None
                    for el in driver.find_elements(By.CSS_SELECTOR, "[role='button']"):
                        displayed, text, cls = _element_probe(el)
                        if (
                            displayed
                            and "Sign in" in text
                            and "uc-button-disabled" not in cls
                        ):
                            sign_in_btn = el
                            break
                    if sign_in_btn is not None:
                        try:
                            sign_in_btn.click()
                        except WebDriverException:
                            # Detached mid-click — rescan next iteration.
                            pass
                        _time.sleep(1)
                        continue

                # 4. Check URL - logged in?
                try:
                    if not driver.current_url.startswith(CONF_OPPO_CLOUD_LOGIN_URL):
                        LOGGER.info("OPPO Cloud login successful")
                        self._persist_cookies(driver)
                        return
                except WebDriverException:
                    pass

                _time.sleep(1)
            else:
                # Deadline hit without success. Before reporting a generic
                # auth error, re-check for a verification widget that may
                # have appeared while we were looping — report it precisely.
                kind = self._scan_for_verification(
                    driver, restore_frame=login_iframe
                )
                if kind is not None:
                    self._raise_verification_required(driver, kind)
                captured = driver.execute_script("return window.__capturedErrors || []")
                body = _body_text(driver, 300)
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
        """Authenticate — preserves session on SMS/verification for retry."""
        try:
            await self.async_login_oppo_cloud(sms_code)
        except (
            OppoCloudApiClientSmsVerificationError,
            OppoCloudApiClientVerificationRequiredError,
        ):
            raise
        except Exception:
            await self.async_cleanup()
            raise

    async def async_get_data(self) -> list[OppoCloudDevice]:
        """Get device location data from OPPO Cloud."""
        sms_pending = False
        verify_pending = False
        try:
            if not self._keep_session:
                # not keeping session, must login every time
                await self.async_login_oppo_cloud()
            return await self._async_fetch_devices()
        except OppoCloudApiClientVerificationRequiredError:
            # Keep the browser session so the human can complete the
            # verification in the noVNC view and the next run resumes.
            verify_pending = True
            raise
        except OppoCloudApiClientSmsVerificationError:
            # Keep the browser session so the SMS code can be entered later.
            sms_pending = True
            raise
        except OppoCloudApiClientAuthenticationError:
            # Not logged in (or session dropped): one explicit re-login retry.
            LOGGER.info("OPPO Cloud not logged in, attempting to log in")
            try:
                await self.async_login_oppo_cloud()
            except OppoCloudApiClientSmsVerificationError:
                sms_pending = True
                raise
            except OppoCloudApiClientVerificationRequiredError:
                verify_pending = True
                raise
            return await self._async_fetch_devices()
        finally:
            # If not keeping session, cleanup after data fetch — unless an SMS
            # or manual verification is pending and needs the preserved session.
            if not self._keep_session and not sms_pending and not verify_pending:
                await self.async_cleanup()

    async def _async_fetch_devices(self) -> list[OppoCloudDevice]:
        """Run the synchronous device scrape in the executor."""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._get_devices_data
            )
        except (
            OppoCloudApiClientAuthenticationError,
            OppoCloudApiClientSmsVerificationError,
        ):
            raise
        except TimeoutException as exception:
            msg = f"get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception
        except Exception as exception:
            msg = f"Unexpected get_devices_data - {exception}"
            raise OppoCloudApiClientError(msg) from exception

    def _get_devices_data(self) -> list[OppoCloudDevice]:
        """Get device locations using Selenium WebDriver."""
        driver = self._get_or_create_driver()
        driver.get(CONF_OPPO_CLOUD_FIND_URL)
        wait = WebDriverWait(driver, 10)  # default timeout

        # The find page is a SPA: the authenticated app object ($findVm) needs
        # a moment to boot, and an expired session bounces to the login page
        # asynchronously. Wait for one of the two outcomes before judging.
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return !!window.$findVm")
                or "login" in (d.current_url or "")
            )
        except TimeoutException:
            pass

        # Check if redirected to login page
        if not driver.current_url.startswith(CONF_OPPO_CLOUD_FIND_URL):
            msg = "not logged in or page redirected unexpectedly"
            raise OppoCloudApiClientAuthenticationError(msg)
        if not driver.execute_script("return !!window.$findVm"):
            # Still on the find URL but the app never booted — treat as
            # auth/session loss (the SPA redirect is just slow), so the
            # caller re-logins instead of silently reporting zero devices.
            msg = "find page did not expose $findVm (session likely expired)"
            raise OppoCloudApiClientAuthenticationError(msg)

        # Wait for the page to finish refreshing GPS locations from phones.
        # otherwise we get old, server-side cached old data

        # Step 1: Wait for the loading overlay (div.device_location) to hide
        def _overlay_gone(d) -> bool:
            els = d.find_elements(By.CSS_SELECTOR, "div.device_location")
            if not els:
                return True
            try:
                return els[0].value_of_css_property("display") == "none"
            except WebDriverException:
                return True

        try:
            wait.until(_overlay_gone)
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
        except TimeoutException:
            device_items = []
            LOGGER.warning("No device items found to click for details")
        for item in device_items:
            try:
                driver.execute_script("arguments[0].click();", item)
            except WebDriverException as exception:
                LOGGER.debug("Device item click failed: %s", exception)
                continue
            with contextlib.suppress(TimeoutException):
                WebDriverWait(driver, 8).until(
                    expected_conditions.presence_of_element_located(
                        (By.CSS_SELECTOR, ".battery-wrapper")
                    )
                )
            time.sleep(1)

        # Now read the fresh data from $findVm + battery from DOM
        device_data = driver.execute_script(
            """
            if (!window.$findVm || !window.$findVm.deviceList) return null;
            var devices = JSON.parse(JSON.stringify(window.$findVm.deviceList));

            function _b(el) {
                return (el.innerText || el.textContent)
                    .replace('%', '').trim();
            }

            var globalBatt = null;
            var battEl = document.querySelector('.battery-wrapper');
            if (battEl) { globalBatt = _b(battEl); }

            var lis = document.querySelectorAll(
                "#device-list .device-list ul > li");
            for (var i = 0; i < devices.length; i++) {
                var local = null;
                if (lis && lis.length > i) {
                    local = lis[i].querySelector('.battery-wrapper');
                }
                if (local) {
                    devices[i]._domBattery = _b(local);
                } else if (globalBatt) {
                    devices[i]._domBattery = globalBatt;
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

        LOGGER.info("Found %d devices in OPPO Cloud", len(devices))
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

            battery_level_raw = (
                device.get("_domBattery")
                or device.get("batteryLevel")
                or device.get("batteryPercent")
            )

            battery_level = None
            if battery_level_raw is not None:
                with contextlib.suppress(ValueError, TypeError):
                    battery_level = int(str(battery_level_raw).replace("%", "").strip())

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
