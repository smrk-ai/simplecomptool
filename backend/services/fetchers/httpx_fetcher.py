"""
Httpx Fetcher - Wiederverwendbarer HTTP Client für URL-Fetching
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import httpx

from .types import FetchResult

logger = logging.getLogger(__name__)

# Konfiguration (aus crawler.py übernommen)
CONNECT_TIMEOUT = 5.0  # Connect-Timeout: 5 Sekunden
READ_TIMEOUT = 15.0  # Read-Timeout: 15 Sekunden
MAX_RETRIES = 2
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


class HttpxFetcher:
    """
    Fetcht URLs mit httpx und einem wiederverwendbaren AsyncClient.

    Der Client wird einmal pro Scan erstellt und wiederverwendet für alle httpx Fetches.
    Implementiert Context Manager für garantierte Ressourcen-Freigabe.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Context Manager Entry - stellt Client bereit"""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context Manager Exit - schließt Client garantiert"""
        await self.close()

    async def _ensure_client(self):
        """Stellt sicher, dass ein Client verfügbar ist"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT),
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT}
            )
            logger.debug("Httpx client created")

    async def close(self):
        """Schließt den Client"""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.debug("Httpx client closed")

    async def fetch(self, url: str) -> FetchResult:
        """
        Fetcht eine URL mit httpx und retries.

        Args:
            url: Die zu fetchende URL

        Returns:
            FetchResult
        """
        await self._ensure_client()

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.get(url)

                # Content-Type ermitteln
                content_type = response.headers.get('content-type', 'text/html')

                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status=response.status_code,
                    headers=dict(response.headers),
                    html=response.text,
                    fetched_at=datetime.now().isoformat(),
                    via='httpx',
                    content_type=content_type
                )

            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    logger.error(f"httpx fetch failed for {url}: {e}")
                    raise
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
