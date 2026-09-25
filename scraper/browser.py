"""Playwright browser lifecycle with stealth configuration."""

import logging
import random

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

from config import settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages a Playwright browser and its contexts with anti-detection.

    The fingerprint is randomized per context, but kept *internally consistent*:
    Chromium user agents only (a Firefox UA on Chromium contradicts the real
    JS/TLS fingerprint), and a timezone that matches the region being scraped
    rather than a hardcoded America/New_York.
    """

    def __init__(
        self,
        headless: bool | None = None,
        proxy: dict | None = None,
        locale: str | None = None,
        timezone_id: str | None = None,
    ):
        self.headless = settings.HEADLESS if headless is None else headless
        self.proxy = proxy
        self.locale = locale or settings.DEFAULT_LOCALE
        self.timezone_id = timezone_id or settings.DEFAULT_TIMEZONE

        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def set_region(self, lng: float | None):
        """Align the browser timezone with the longitude being scraped."""
        self.timezone_id = settings.timezone_for_longitude(lng)

    async def start(self) -> Page:
        """Launch the browser and return a stealth page."""
        self._playwright = await async_playwright().start()
        launch_kwargs = {
            "headless": self.headless,
            "args": settings.BROWSER_ARGS,
        }
        if self.proxy:
            # Proxy goes on the launch so it also covers the initial connection.
            launch_kwargs["proxy"] = self.proxy
            logger.info(f"Using proxy: {self.proxy.get('server')}")

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        return await self.new_context()

    async def new_context(self) -> Page:
        """Create a fresh browser context with a randomized fingerprint."""
        await self._close_context()

        viewport = {
            "width": random.randint(*settings.VIEWPORT_WIDTH_RANGE),
            "height": random.randint(*settings.VIEWPORT_HEIGHT_RANGE),
        }
        user_agent = random.choice(settings.USER_AGENTS)

        context_kwargs = {
            "viewport": viewport,
            "user_agent": user_agent,
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "geolocation": None,
            "permissions": [],
        }
        if self.proxy:
            context_kwargs["proxy"] = self.proxy

        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_navigation_timeout(settings.NAV_TIMEOUT_MS)

        # playwright-stealth 2.x: Stealth().apply_stealth_async (replaces the
        # removed module-level stealth_async).
        await Stealth().apply_stealth_async(self._context)
        self._page = await self._context.new_page()

        logger.info(
            f"New context: {viewport['width']}x{viewport['height']}, "
            f"tz={self.timezone_id}, UA={user_agent[:48]}..."
        )
        return self._page

    async def _close_context(self):
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug(f"Context close failed: {exc}")
            self._context = None
            self._page = None

    @property
    def page(self) -> Page | None:
        return self._page

    async def close(self):
        """Clean shutdown. Every stage is independently guarded so a failure
        in one does not leak the others."""
        await self._close_context()
        for closer, name in (
            (getattr(self._browser, "close", None), "browser"),
            (getattr(self._playwright, "stop", None), "playwright"),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception as exc:
                logger.debug(f"{name} shutdown failed: {exc}")
        self._browser = None
        self._playwright = None
        logger.info("Browser closed.")
