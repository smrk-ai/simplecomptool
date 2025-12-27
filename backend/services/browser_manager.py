import asyncio
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser
import logging

logger = logging.getLogger(__name__)

class BrowserManager:
    """Thread-safe Browser Pool Manager"""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._browser_started = False

    @asynccontextmanager
    async def get_browser(self):
        """
        Thread-safe Browser Zugriff.
        Usage:
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
        """
        async with self._lock:
            if not self._browser_started:
                logger.info("Starting Playwright browser...")
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage'
                    ]
                )
                self._browser_started = True
                logger.info("✅ Browser started")

            try:
                yield self._browser
            except Exception as e:
                logger.error(f"Browser error: {e}")
                raise

    async def close(self):
        """Shutdown Browser"""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            self._browser_started = False
            logger.info("Browser closed")

# Global Instance
browser_manager = BrowserManager()

