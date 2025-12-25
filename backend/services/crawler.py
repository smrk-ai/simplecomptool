import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konfiguration
CONNECT_TIMEOUT = 5.0  # Connect-Timeout: 5 Sekunden
READ_TIMEOUT = 15.0  # Read-Timeout: 15 Sekunden
MAX_RETRIES = 2
MAX_URLS = 20
MAX_CONCURRENT_FETCHES = 5  # Max 5 parallele Fetches

# User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Browser-Pool für Playwright (wiederverwendbar)
_browser_pool = None
_playwright_instance = None

# Playwright-Usage Counter (für Logging)
_playwright_usage_count = 0

# Keywords für Priorisierung
PRIORITY_KEYWORDS = [
    'pricing', 'plan', 'product', 'features', 'solutions',
    'customers', 'case-study', 'docs', 'blog', 'changelog',
    'news', 'careers', 'jobs', 'about', 'company', 'team',
    'security', 'privacy', 'terms'
]

# Zu filternde Pfade
FILTERED_PATHS = [
    'logout', 'login', 'cart', 'checkout', 'private',
    'admin', 'wp-admin', 'wp-login', 'signin', 'signup'
]

# Zu filternde Dateiendungen
FILTERED_EXTENSIONS = [
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.zip',
    '.rar', '.7z', '.mp4', '.mp3', '.avi', '.mov', '.wmv',
    '.exe', '.dmg', '.deb', '.rpm', '.css', '.js', '.ico'
]


def normalize_url(url: str, base_url: str = None) -> str:
    """
    Normalisiert eine URL:
    - Fügt HTTPS hinzu, wenn kein Schema vorhanden
    - Konvertiert HTTP zu HTTPS
    - Entfernt Fragments (#)
    - Entfernt Tracking-Parameter (utm_*, fbclid, gclid)
    - Resolved relative URLs
    """
    try:
        if base_url:
            url = urljoin(base_url, url)

        parsed = urlparse(url)

        # Wenn kein Schema vorhanden, HTTPS hinzufügen
        if not parsed.scheme:
            # Wenn netloc vorhanden (z.B. "grafiklabor.de"), dann ist es eine Domain
            if parsed.netloc:
                parsed = parsed._replace(scheme='https')
            # Sonst könnte es ein relativer Pfad sein - füge https:// hinzu
            elif url and not url.startswith('/'):
                url = f"https://{url}"
                parsed = urlparse(url)

        # HTTPS erzwingen (falls HTTP vorhanden)
        if parsed.scheme == 'http':
            parsed = parsed._replace(scheme='https')

        # Fragment entfernen
        parsed = parsed._replace(fragment='')

        # Query-Parameter filtern
        if parsed.query:
            query_params = parse_qs(parsed.query)
            filtered_params = {
                k: v for k, v in query_params.items()
                if not (k.startswith('utm_') or k in ['fbclid', 'gclid'])
            }
            if filtered_params:
                parsed = parsed._replace(query=urlencode(filtered_params, doseq=True))
            else:
                parsed = parsed._replace(query='')

        return urlunparse(parsed)
    except Exception as e:
        logger.warning(f"Fehler beim Normalisieren der URL {url}: {e}")
        return url


def is_same_domain(url1: str, url2: str) -> bool:
    """
    Prüft, ob zwei URLs die gleiche Domain haben (inkl. www-Variante)
    """
    try:
        domain1 = urlparse(url1).netloc.lower().replace('www.', '')
        domain2 = urlparse(url2).netloc.lower().replace('www.', '')
        return domain1 == domain2
    except:
        return False


def should_filter_url(url: str, base_domain: str) -> bool:
    """
    Prüft, ob eine URL gefiltert werden sollte
    """
    try:
        parsed = urlparse(url)

        # Domain-Check
        if not is_same_domain(url, f"https://{base_domain}"):
            logger.debug(f"URL gefiltert (Domain-Mismatch): {url}")
            return True

        # Pfad-Check
        path_lower = parsed.path.lower()
        if any(filtered_path in path_lower for filtered_path in FILTERED_PATHS):
            logger.debug(f"URL gefiltert (Pfad): {url}")
            return True

        # Dateiendung-Check
        if any(parsed.path.lower().endswith(ext) for ext in FILTERED_EXTENSIONS):
            logger.debug(f"URL gefiltert (Dateiendung): {url}")
            return True

        # Query-Parameter für statische Assets
        if parsed.query and any(ext in parsed.query.lower() for ext in FILTERED_EXTENSIONS):
            logger.debug(f"URL gefiltert (Query-Parameter): {url}")
            return True

        logger.debug(f"URL akzeptiert: {url}")
        return False
    except Exception as e:
        logger.warning(f"Fehler beim Filtern der URL {url}: {e}")
        return True


def calculate_priority(url: str, anchor_text: str = "") -> int:
    """
    Berechnet Priorität einer URL basierend auf Keywords
    """
    priority = 0
    url_lower = url.lower()
    anchor_lower = anchor_text.lower()

    for keyword in PRIORITY_KEYWORDS:
        if keyword in url_lower or keyword in anchor_lower:
            priority += 1

    return priority


def extract_links(html: str, base_url: str) -> List[Tuple[str, str]]:
    """
    Extrahiert Links aus HTML und gibt (url, anchor_text) zurück
    """
    links = []
    try:
        soup = BeautifulSoup(html, 'lxml')

        # Alle <a> Tags finden
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            text = a_tag.get_text(strip=True) or ""
            links.append((href, text))

        # Zusätzlich Navigation und Footer durchsuchen
        for selector in ['nav', 'footer', '.navigation', '.nav', '.menu', '.footer']:
            elements = soup.select(selector)
            for element in elements:
                for a_tag in element.find_all('a', href=True):
                    href = a_tag.get('href')
                    text = a_tag.get_text(strip=True) or ""
                    links.append((href, text))

    except Exception as e:
        logger.warning(f"Fehler beim Extrahieren von Links: {e}")

    return links


def requires_javascript(html: str) -> bool:
    """
    Prüft, ob eine Seite wahrscheinlich JavaScript benötigt
    Weniger aggressiv: Nur wenn wirklich wenig Text UND viele Scripts
    """
    try:
        soup = BeautifulSoup(html, 'lxml')

        # Entferne Script-Tags und Style-Tags für Textanalyse
        for script in soup(["script", "style"]):
            script.extract()

        text_content = soup.get_text()
        text_length = len(text_content.strip())

        # Zähle Script-Tags
        script_count = len(soup.find_all('script'))

        # Weniger aggressiv: Nur wenn wirklich wenig Text (< 200 chars) UND viele Scripts (> 5)
        return text_length < 200 and script_count > 5

    except Exception as e:
        logger.warning(f"Fehler bei JS-Detection: {e}")
        return False


async def fetch_with_httpx(url: str) -> Dict:
    """
    Fetcht eine URL mit httpx (async mit retries)
    Konfigurierte Timeouts: connect 5s, read 15s
    """
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT),
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT}
            ) as client:
                response = await client.get(url)

                return {
                    'final_url': str(response.url),
                    'status': response.status_code,
                    'headers': dict(response.headers),
                    'html': response.text,
                    'fetched_at': datetime.now().isoformat(),
                    'via': 'httpx'
                }

        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logger.error(f"httpx fetch fehlgeschlagen für {url}: {e}")
                raise
            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff


async def get_browser_pool():
    """
    Wiederverwendbarer Browser-Pool für Playwright
    Vermeidet wiederholtes Browser-Startup
    """
    global _browser_pool, _playwright_instance
    
    if _browser_pool is None:
        _playwright_instance = await async_playwright().start()
        _browser_pool = await _playwright_instance.chromium.launch(headless=True)
        logger.info("Playwright Browser-Pool initialisiert")
    
    return _browser_pool


async def fetch_with_playwright(url: str) -> Dict:
    """
    Fetcht eine URL mit Playwright (für JS-required Seiten)
    Optimiert: Browser-Pool wiederverwenden, schnelleres Wait-Strategy
    """
    global _playwright_usage_count
    _playwright_usage_count += 1
    
    browser = await get_browser_pool()
    context = await browser.new_context(
        user_agent=USER_AGENT
    )
    page = await context.new_page()

    try:
        # Schnelleres Wait-Strategy: domcontentloaded statt networkidle
        # Timeout basierend auf READ_TIMEOUT
        await page.goto(url, wait_until="domcontentloaded", timeout=int(READ_TIMEOUT * 1000))
        await page.wait_for_timeout(500)  # Reduziert von 2000ms auf 500ms

        content = await page.content()

        return {
            'final_url': page.url,
            'status': 200,  # Playwright gibt keinen HTTP-Status zurück
            'headers': {},  # Playwright gibt keine Headers zurück
            'html': content,
            'fetched_at': datetime.now().isoformat(),
            'via': 'playwright'
        }

    except Exception as e:
        logger.error(f"Playwright fetch fehlgeschlagen für {url}: {e}")
        raise
    finally:
        await context.close()


def get_playwright_usage_count() -> int:
    """Gibt die Anzahl der Playwright-Aufrufe zurück (für Logging)"""
    return _playwright_usage_count


def reset_playwright_usage_count():
    """Setzt den Playwright-Usage-Counter zurück"""
    global _playwright_usage_count
    _playwright_usage_count = 0


async def fetch_url(url: str) -> Dict:
    """
    Fetcht eine URL mit httpx, Playwright nur bei JS-required Seiten
    Kein Fallback mehr auf Playwright bei httpx-Fehlern (Performance)

    Returns:
        {
            'final_url': str,
            'status': int,
            'headers': dict,
            'html': str,
            'fetched_at': str,
            'via': 'httpx' | 'playwright'
        }
    """
    try:
        # Zuerst mit httpx versuchen
        result = await fetch_with_httpx(url)

        # Nur bei wirklich JS-required Seiten Playwright verwenden
        if requires_javascript(result['html']):
            logger.info(f"JS erforderlich für {url}, verwende Playwright")
            result = await fetch_with_playwright(url)

        return result

    except Exception as e:
        # KEIN Playwright-Fallback mehr - einfach Fehler zurückgeben
        # Playwright ist zu langsam als Fallback
        logger.error(f"httpx fehlgeschlagen für {url}: {e}")
        raise


async def discover_urls(start_url: str) -> List[str]:
    """
    Entdeckt URLs innerhalb der gleichen Domain

    Args:
        start_url: Die Start-URL für den Crawl

    Returns:
        Liste von bis zu MAX_URLS canonical URLs innerhalb derselben Domain
    """
    logger.info(f"Starte URL-Discovery für: {start_url}")

    try:
        # Start-URL normalisieren
        normalized_start = normalize_url(start_url)
        base_domain = urlparse(normalized_start).netloc
        
        # Validierung: base_domain muss vorhanden sein
        if not base_domain:
            logger.error(f"Konnte Domain nicht aus URL extrahieren: {normalized_start}")
            return [normalized_start]  # Fallback: Start-URL zurückgeben

        # Startseite fetchen
        logger.info(f"Fetche Start-URL: {normalized_start}")
        start_result = await fetch_url(normalized_start)
        if start_result['status'] != 200:
            logger.error(f"Start-URL {normalized_start} returned status {start_result['status']}")
            return []
        
        logger.info(f"Start-URL erfolgreich gefetcht, HTML-Länge: {len(start_result['html'])} Zeichen")

        # Links extrahieren
        links = extract_links(start_result['html'], normalized_start)
        logger.info(f"Extrahierte {len(links)} Links von Startseite")

        # URLs verarbeiten und priorisieren
        url_scores = {}  # url -> (priority, anchor_text)
        seen_urls = set()
        filtered_count = 0

        for href, anchor_text in links:
            try:
                normalized_url = normalize_url(href, normalized_start)

                # Duplikate vermeiden
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)

                # Filtern
                if should_filter_url(normalized_url, base_domain):
                    filtered_count += 1
                    continue

                # Priorität berechnen
                priority = calculate_priority(normalized_url, anchor_text)

                # Beste Priorität für jede URL behalten
                if normalized_url not in url_scores or priority > url_scores[normalized_url][0]:
                    url_scores[normalized_url] = (priority, anchor_text)

            except Exception as e:
                logger.warning(f"Fehler beim Verarbeiten von Link {href}: {e}")
                continue

        logger.info(f"URL-Verarbeitung: {len(url_scores)} URLs akzeptiert, {filtered_count} gefiltert")

        # URLs nach Priorität sortieren (höchste zuerst)
        sorted_urls = sorted(
            url_scores.items(),
            key=lambda x: x[1][0],  # Sortiere nach Priorität
            reverse=True
        )

        # Top URLs auswählen (max MAX_URLS)
        result_urls = [url for url, _ in sorted_urls[:MAX_URLS]]

        # Start-URL immer zuerst (falls nicht schon dabei)
        if normalized_start not in result_urls:
            result_urls.insert(0, normalized_start)

        logger.info(f"Discovery abgeschlossen: {len(result_urls)} URLs für Domain {base_domain} (von {len(links)} Links, {len(url_scores)} akzeptiert, {filtered_count} gefiltert)")
        
        # Stelle sicher, dass mindestens die Start-URL zurückgegeben wird
        if not result_urls:
            logger.warning(f"Keine URLs gefunden, aber Start-URL sollte vorhanden sein: {normalized_start}")
            result_urls = [normalized_start]
        
        return result_urls[:MAX_URLS]

    except Exception as e:
        logger.error(f"Fehler bei URL-Discovery für {start_url}: {e}", exc_info=True)
        # Fallback: Versuche zumindest die normalisierte Start-URL zurückzugeben
        try:
            normalized_start = normalize_url(start_url)
            logger.info(f"Fallback: Gebe normalisierte Start-URL zurück: {normalized_start}")
            return [normalized_start]
        except Exception as fallback_error:
            logger.error(f"Konnte auch Fallback-URL nicht normalisieren: {fallback_error}")
            return []
