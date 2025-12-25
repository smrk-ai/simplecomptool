"""
Fetch Manager - Orchestriert verschiedene Fetcher und entscheidet Render-Mode
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .types import FetchResult
from .httpx_fetcher import HttpxFetcher
from .playwright_fetcher import PlaywrightFetcher

logger = logging.getLogger(__name__)


@dataclass
class ScanStats:
    """Statistiken eines Scans"""
    playwright_browser_started: bool
    httpx_pages_count: int
    playwright_pages_count: int
    error: Optional[str] = None


class FetchManager:
    """
    Orchestriert verschiedene Fetcher und entscheidet Render-Mode pro Scan.

    Browser Lifecycle:
    - Playwright Browser wird maximal 1× pro Scan gestartet
    - Browser bleibt während des gesamten Scans aktiv
    - Wird erst am Ende des Scans geschlossen

    httpx Client Lifecycle:
    - httpx Client wird einmal pro Scan erstellt
    - Client wird für alle httpx Fetches wiederverwendet
    - Client wird garantiert am Ende des Scans geschlossen

    Concurrency:
    - httpx: max 5 parallele Fetches
    - playwright: max 2 parallele Page-Fetches
    """

    def __init__(self):
        self.httpx_fetcher = HttpxFetcher()
        self.playwright_fetcher = PlaywrightFetcher()

        # Concurrency Limits
        self.httpx_semaphore = asyncio.Semaphore(5)  # max 5 parallele httpx fetches
        self.playwright_semaphore = asyncio.Semaphore(2)  # max 2 parallele playwright page fetches

    async def __aenter__(self):
        """Context Manager Entry - httpx Client bereitstellen"""
        await self.httpx_fetcher.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context Manager Exit - alle Ressourcen freigeben"""
        # httpx Client schließen
        await self.httpx_fetcher.__aexit__(exc_type, exc_val, exc_tb)

        # Playwright Browser schließen (falls noch offen)
        if self.playwright_fetcher.is_browser_open():
            await self.playwright_fetcher.close_browser()

    async def decide_render_mode(self, start_url: str) -> str:
        """
        Entscheidet den Render-Mode für einen Scan basierend auf der Start-URL.

        Heuristik:
        1. Lade start_url via httpx
        2. Extrahiere quick_text aus HTML (max 5.000 chars)
        3. Entscheidung:
           - Wenn quick_text < 500 chars ODER SPA-Marker vorhanden: "hybrid"
           - Wenn httpx fehlschlägt oder 403/429: "playwright"
           - Sonst: "httpx"

        Returns:
            "httpx" | "playwright" | "hybrid"
        """
        try:
            # Lade Start-URL via httpx
            fetch_result = await self.httpx_fetcher.fetch(start_url)

            if fetch_result.status >= 400:
                # httpx fehlgeschlagen oder 403/429
                logger.info(f"httpx failed for start_url (status {fetch_result.status}), using playwright")
                return "playwright"

            # Extrahiere quick_text
            quick_text = self._extract_quick_text(fetch_result.html)
            has_spa_markers = self._has_spa_markers(fetch_result.html)

            logger.info(f"Quick text length: {len(quick_text)}, SPA markers: {has_spa_markers}")

            # Entscheidung
            if len(quick_text) < 500 or has_spa_markers:
                return "hybrid"
            else:
                return "httpx"

        except Exception as e:
            logger.warning(f"Error deciding render mode, falling back to playwright: {e}")
            return "playwright"

    async def fetch_with_mode(self, url: str, mode: str) -> FetchResult:
        """
        Fetcht eine URL mit dem angegebenen Mode.

        Args:
            url: Die zu fetchende URL
            mode: "httpx", "playwright", oder "hybrid"

        Returns:
            FetchResult
        """
        if mode == "httpx":
            async with self.httpx_semaphore:
                return await self.httpx_fetcher.fetch(url)

        elif mode == "playwright":
            # Stelle sicher, dass Browser geöffnet ist
            if not self.playwright_fetcher.is_browser_open():
                await self.playwright_fetcher.open_browser()

            async with self.playwright_semaphore:
                return await self.playwright_fetcher.fetch(url)

        elif mode == "hybrid":
            # Zuerst httpx versuchen
            try:
                async with self.httpx_semaphore:
                    httpx_result = await self.httpx_fetcher.fetch(url)

                # Prüfe quick_text Länge
                quick_text = self._extract_quick_text(httpx_result.html)

                if len(quick_text) < 300:
                    # Zu wenig Content, verwende Playwright
                    logger.info(f"Hybrid mode: switching to playwright for {url} (quick_text: {len(quick_text)} chars)")
                    if not self.playwright_fetcher.is_browser_open():
                        await self.playwright_fetcher.open_browser()

                    async with self.playwright_semaphore:
                        return await self.playwright_fetcher.fetch(url)
                else:
                    # httpx Ergebnis ist ausreichend
                    return httpx_result

            except Exception as e:
                # httpx fehlgeschlagen, fallback auf playwright
                logger.warning(f"Hybrid mode: httpx failed for {url}, falling back to playwright: {e}")
                if not self.playwright_fetcher.is_browser_open():
                    await self.playwright_fetcher.open_browser()

                async with self.playwright_semaphore:
                    return await self.playwright_fetcher.fetch(url)

        else:
            raise ValueError(f"Unknown mode: {mode}")

    async def fetch_urls(self, urls: List[str], mode: str) -> Tuple[List[FetchResult], ScanStats]:
        """
        Fetcht alle URLs mit dem angegebenen Mode und Concurrency-Limits.

        Args:
            urls: Liste der zu fetchenden URLs
            mode: Render-Mode ("httpx", "playwright", "hybrid")

        Returns:
            Tuple[List[FetchResult], ScanStats]
        """
        playwright_browser_started = False
        httpx_pages_count = 0
        playwright_pages_count = 0
        error = None

        async def fetch_single(url: str) -> FetchResult:
            nonlocal playwright_browser_started, httpx_pages_count, playwright_pages_count, error

            try:
                result = await self.fetch_with_mode(url, mode)

                if result.via == "httpx":
                    httpx_pages_count += 1
                elif result.via == "playwright":
                    playwright_pages_count += 1
                    playwright_browser_started = True

                return result

            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                error = str(e)
                # Return dummy result for failed fetches
                return FetchResult(
                    url=url,
                    final_url=url,
                    status=0,
                    headers={},
                    html="",
                    fetched_at=datetime.now().isoformat(),
                    via="error"
                )

        # Alle URLs parallel fetchen
        logger.info(f"Fetching {len(urls)} URLs with mode '{mode}'")
        results = await asyncio.gather(*[fetch_single(url) for url in urls])

        stats = ScanStats(
            playwright_browser_started=playwright_browser_started,
            httpx_pages_count=httpx_pages_count,
            playwright_pages_count=playwright_pages_count,
            error=error
        )

        logger.info(f"Fetch completed: httpx={httpx_pages_count}, playwright={playwright_pages_count}, browser_started={playwright_browser_started}")

        # Hinweis: Browser und httpx Client werden automatisch via Context Manager geschlossen
        return results, stats

    def _extract_quick_text(self, html: str) -> str:
        """
        Extrahiert quick_text aus HTML für Render-Mode Entscheidung.

        - Entfernt <script>, <style> Tags
        - Extrahiert sichtbaren Text
        - Max 5.000 Zeichen

        Returns:
            Normalisierter Text
        """
        try:
            soup = BeautifulSoup(html, 'lxml')

            # Entferne script und style Tags
            for tag in soup(['script', 'style']):
                tag.extract()

            # Extrahiere Text
            text = soup.get_text()

            # Normalisiere Whitespace
            import re
            text = re.sub(r'\s+', ' ', text.strip())

            # Begrenze Länge
            return text[:5000]

        except Exception as e:
            logger.warning(f"Error extracting quick text: {e}")
            return ""

    def _has_spa_markers(self, html: str) -> bool:
        """
        Prüft auf SPA-Marker in HTML.

        Marker:
        - id="__next" (Next.js)
        - id="root" (React)
        - data-reactroot (React)
        - "webpack" im HTML
        - "next/script" im HTML
        """
        html_lower = html.lower()
        markers = [
            'id="__next"',
            'id="root"',
            'data-reactroot',
            'webpack',
            'next/script'
        ]

        return any(marker in html_lower for marker in markers)
