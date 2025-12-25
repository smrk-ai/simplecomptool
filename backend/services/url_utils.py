"""
URL Utilities - Normalisierung und Validierung von URLs
"""

from urllib.parse import urlparse, urlunparse
from typing import Optional


def normalize_input_url(raw: str) -> str:
    """
    Normalisiert eine Benutzereingabe-URL zu einer kanonischen Base-URL.

    Regeln:
    1) Trim whitespace
    2) Wenn kein Schema vorhanden: prepend "https://"
    3) Parse URL, erlaube nur http/https
    4) Entferne path/query/fragment für base_url
    5) Lower-case host, entferne trailing slash
    6) Normalisiere "www.": einheitlich entfernen (für einfachere Deduplizierung)
    7) Wenn parsing fehlschlägt: raise ValueError mit klarer Message

    Args:
        raw: Die rohe Benutzereingabe

    Returns:
        Die normalisierte Base-URL (z.B. "https://example.com")

    Raises:
        ValueError: Bei ungültiger URL mit beschreibender Nachricht
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("URL darf nicht leer sein")

    # 1) Trim whitespace
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("URL darf nicht leer sein")

    # 2) Wenn kein Schema vorhanden: prepend "https://"
    import re
    if not re.match(r'^https?://', trimmed):
        # Prüfe ob es wie eine URL aussieht (enthält Punkt)
        if '.' not in trimmed:
            raise ValueError(f"Ungültige URL: '{trimmed}' - scheint keine gültige Domain zu sein")
        trimmed = f"https://{trimmed}"

    # 3) Parse URL
    try:
        parsed = urlparse(trimmed)
    except Exception as e:
        raise ValueError(f"URL-Parsing fehlgeschlagen für '{raw}': {str(e)}")

    # Validiere Schema
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Nur HTTP/HTTPS URLs erlaubt, erhalten: '{parsed.scheme}'")

    # Validiere Host
    if not parsed.hostname:
        raise ValueError(f"Keine gültige Domain gefunden in '{raw}'")

    # 6) Normalisiere "www.": einheitlich entfernen für einfachere Deduplizierung
    hostname = parsed.hostname.lower()
    if hostname.startswith('www.'):
        hostname = hostname[4:]  # Entferne "www."

    # 4) Entferne path/query/fragment für base_url
    # 5) Lower-case host, entferne trailing slash
    normalized = urlunparse((
        parsed.scheme,
        hostname,
        '',  # path = leer für base_url
        '',  # params = leer
        '',  # query = leer
        ''   # fragment = leer
    ))

    # Entferne trailing slash vom Host-Teil falls vorhanden
    if normalized.endswith('/'):
        normalized = normalized.rstrip('/')

    return normalized


def validate_url_for_scanning(url: str) -> None:
    """
    Zusätzliche Validierung für URLs die gescannt werden sollen.

    Args:
        url: Die zu validierende URL

    Raises:
        ValueError: Bei ungeeigneten URLs für Scanning
    """
    parsed = urlparse(url)

    # Zusätzliche Checks für Scanning
    if parsed.hostname in ('localhost', '127.0.0.1', '::1'):
        raise ValueError("Scannen von localhost ist nicht erlaubt")

    # Bekannte problematische Domains
    blocked_domains = [
        'example.com', 'example.org', 'test.com',
        'invalid', 'localhost.localdomain'
    ]

    if parsed.hostname in blocked_domains:
        raise ValueError(f"Domain '{parsed.hostname}' ist für Tests reserviert und kann nicht gescannt werden")
