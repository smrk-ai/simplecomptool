"""
Playwright Fetcher - Browser-basierter URL Fetcher mit Lifecycle-Management
"""

import logging
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from .types import FetchResult

logger = logging.getLogger(__name__)

# Konfiguration (aus crawler.py übernommen)
READ_TIMEOUT = 15.0  # Read-Timeout: 15 Sekunden
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


class PlaywrightFetcher:
    """
    Fetcht URLs mit Playwright und verwaltet Browser-Lifecycle.

    Browser Lifecycle:
    - Ein Browser + ein Context pro Scan
    - Pro URL wird eine neue Page erstellt und danach geschlossen
    - Browser wird erst am Ende des Scans geschlossen

    Wichtig: Playwright darf nur in diesem Modul gestartet werden.
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def is_browser_open(self) -> bool:
        """Prüft, ob der Browser geöffnet ist"""
        return self._browser is not None

    async def open_browser(self) -> None:
        """Öffnet Browser einmal pro Scan"""
        if self._browser is not None:
            return  # Bereits geöffnet

        logger.debug("Starting Playwright and opening browser...")

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(user_agent=USER_AGENT)

        logger.info("Playwright browser opened")

    async def close_browser(self) -> None:
        """Schließt Browser und räumt auf"""
        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Playwright browser closed")

    async def fetch(self, url: str) -> FetchResult:
        """
        Fetcht eine URL mit Playwright.

        Erstellt eine neue Page aus dem bestehenden Context,
        fetcht die URL und schließt die Page danach.

        Args:
            url: Die zu fetchende URL

        Returns:
            FetchResult

        Raises:
            RuntimeError: Wenn Browser nicht geöffnet ist
        """
        if not self._context:
            raise RuntimeError("Browser not opened. Call open_browser() first.")

        page = await self._context.new_page()

        try:
            # Schnelleres Wait-Strategy: domcontentloaded statt networkidle
            # Timeout basierend auf READ_TIMEOUT
            response = await page.goto(url, wait_until="domcontentloaded", timeout=int(READ_TIMEOUT * 1000))
            await page.wait_for_timeout(500)  # Kurze Wartezeit für JS-Execution

            content = await page.content()

            # Response-Informationen extrahieren
            if response is not None:
                # Erfolgreiche Navigation - echte Response-Daten verwenden
                status = response.status
                headers = dict(response.headers)
                final_url = response.url
            else:
                # Kein Response (z.B. data: URLs, navigation issues)
                status = 0
                headers = {}
                final_url = page.url  # Fallback auf page.url

            # Content-Type aus Headers ableiten (falls vorhanden)
            content_type = headers.get('content-type', 'text/html')

            return FetchResult(
                url=url,
                final_url=final_url,
                status=status,
                headers=headers,
                html=content,
                fetched_at=datetime.now().isoformat(),
                via='playwright',
                content_type=content_type
            )

        except Exception as e:
            logger.error(f"Playwright fetch failed for {url}: {e}")
            raise
        finally:
            await page.close()
