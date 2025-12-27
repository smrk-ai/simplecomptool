"""
URL Utilities - Zentrale URL-Normalisierung

CRITICAL REFACTORING:
Vereinheitlicht die zwei inkonsistenten URL-Normalisierungs-Funktionen:
- crawler.py: normalize_url()
- persistence.py: canonicalize_url()

Diese zentrale Implementierung wird von ALLEN Modulen verwendet.
"""

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, urljoin
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Tracking-Parameter die entfernt werden sollen
TRACKING_PARAMS = [
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'fbclid', 'gclid', 'mc_cid', 'mc_eid', '_ga', 'ref', 'source'
]


def canonicalize_url(url: str, base_url: Optional[str] = None) -> str:
    """
    ZENTRALE URL-Normalisierung für das gesamte System.

    Regeln:
    1. Resolve relative URLs (wenn base_url gegeben)
    2. HTTPS erzwingen (HTTP → HTTPS)
    3. Lowercase domain (example.COM → example.com)
    4. Strip www (www.example.com → example.com)
    5. Remove fragment (#section)
    6. Remove tracking params (utm_*, fbclid, gclid, etc.)
    7. Remove trailing slash (außer root /)
    8. Strip whitespace

    Args:
        url: Die zu normalisierende URL
        base_url: Optional - Base URL für relative URLs

    Returns:
        Kanonische URL

    Beispiel:
        >>> canonicalize_url("https://WWW.Example.COM/page/?utm_source=google#section")
        'https://example.com/page'

        >>> canonicalize_url("/about", "https://example.com")
        'https://example.com/about'
    """
    try:
        # Whitespace entfernen
        url = url.strip()

        # Relative URLs resolven
        if base_url:
            url = urljoin(base_url, url)

        # URL parsen
        parsed = urlparse(url)

        # Schema hinzufügen falls nicht vorhanden
        if not parsed.scheme:
            # Wenn netloc vorhanden → Domain
            if parsed.netloc:
                url = f"https://{url}"
                parsed = urlparse(url)
            # Sonst könnte es relativer Pfad sein
            elif url and not url.startswith('/'):
                url = f"https://{url}"
                parsed = urlparse(url)

        # HTTPS erzwingen (HTTP → HTTPS)
        scheme = 'https'

        # Lowercase domain & strip www
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        # Fragment entfernen
        fragment = ''

        # Tracking-Parameter filtern
        query = ''
        if parsed.query:
            query_params = parse_qs(parsed.query)
            # Filter tracking params
            filtered_params = {}
            for key, value in query_params.items():
                # Blockiere Tracking-Parameter
                if not any(key.lower().startswith(tp.lower()) for tp in TRACKING_PARAMS):
                    filtered_params[key] = value

            # Query-String neu generieren
            if filtered_params:
                query = urlencode(filtered_params, doseq=True)

        # Trailing slash entfernen (außer root)
        path = parsed.path
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')

        # URL zusammenbauen
        canonical = urlunparse((
            scheme,
            netloc,
            path,
            '',      # params (leer)
            query,
            fragment
        ))

        return canonical

    except Exception as e:
        logger.warning(f"URL normalization failed for {url}: {e}")
        return url


def is_same_domain(url1: str, url2: str) -> bool:
    """
    Prüft, ob zwei URLs die gleiche Domain haben (inkl. www-Variante).

    Args:
        url1: Erste URL
        url2: Zweite URL

    Returns:
        True wenn gleiche Domain, sonst False

    Beispiel:
        >>> is_same_domain("https://www.example.com/page", "https://example.com/other")
        True
    """
    try:
        domain1 = urlparse(url1).netloc.lower().replace('www.', '')
        domain2 = urlparse(url2).netloc.lower().replace('www.', '')
        return domain1 == domain2
    except Exception as e:
        logger.warning(f"Domain comparison failed: {e}")
        return False


def get_base_url(url: str) -> str:
    """
    Extrahiert die Base URL (scheme + domain) aus einer URL.

    Args:
        url: Vollständige URL

    Returns:
        Base URL (scheme://domain)

    Beispiel:
        >>> get_base_url("https://example.com/page?param=value")
        'https://example.com'
    """
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception as e:
        logger.warning(f"Base URL extraction failed for {url}: {e}")
        return url
