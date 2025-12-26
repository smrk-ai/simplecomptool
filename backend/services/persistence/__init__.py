"""
Persistence Services Package
"""

from .base import Store
from .store_factory import get_store
from .sqlite_store import SQLiteStore
from .supabase_store import SupabaseStore
import re
import logging
import hashlib
from typing import Tuple
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
MAX_TEXT_LENGTH = 50000  # Konstante für Text-Längenbegrenzung

def extract_text_from_html(html: str) -> Tuple[str, str, str]:
    """
    Extrahiert Titel, Meta-Description und normalisierten Text aus HTML

    Returns:
        (title, meta_description, normalized_text)
    """
    try:
        soup = BeautifulSoup(html, 'lxml')

        # Titel extrahieren
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()

        # Meta description extrahieren
        meta_description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            meta_description = meta_desc['content'].strip()

        # Haupttext extrahieren
        # Entferne script, style, noscript Tags
        for tag in soup(['script', 'style', 'noscript']):
            tag.extract()

        # Extrahiere sichtbaren Text
        text = soup.get_text()

        # Normalisiere Whitespace
        # Mehrere Leerzeichen/Zeilen zu einem zusammenfassen
        normalized_text = re.sub(r'\s+', ' ', text.strip())

        # Begrenze Länge
        if len(normalized_text) > MAX_TEXT_LENGTH:
            normalized_text = normalized_text[:MAX_TEXT_LENGTH]

        return title, meta_description, normalized_text

    except Exception as e:
        logger.warning(f"Fehler bei Text-Extraktion: {e}")
        return "", "", ""


def calculate_text_hash(text: str) -> str:
    """Berechnet SHA-256 Hash des Textes"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonicalize_url(url: str) -> str:
    """
    Erstellt eine kanonische URL für Change Detection.

    Normalisierung:
    - Schema erzwingen (https)
    - Host normalisieren (www entfernen)
    - Fragment entfernen (#)
    - Tracking-Parameter entfernen (utm_*, fbclid, gclid, etc.)
    - Query-Parameter sortieren für Determinismus
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Schema erzwingen
        if parsed.scheme != 'https':
            parsed = parsed._replace(scheme='https')

        # Host normalisieren (www entfernen)
        if parsed.hostname and parsed.hostname.startswith('www.'):
            parsed = parsed._replace(netloc=parsed.hostname[4:])

        # Fragment entfernen
        parsed = parsed._replace(fragment='')

        # Query-Parameter filtern und sortieren
        if parsed.query:
            query_params = parse_qs(parsed.query, keep_blank_values=False)
            # Tracking-Parameter entfernen
            filtered_params = {
                k: v for k, v in query_params.items()
                if not any(k.startswith(prefix) for prefix in ['utm_', 'fbclid', 'gclid', 'gclsrc', '_ga'])
            }
            if filtered_params:
                # Sortiere Parameter für Determinismus
                sorted_params = sorted(filtered_params.items())
                parsed = parsed._replace(query=urlencode(sorted_params, doseq=True))
            else:
                parsed = parsed._replace(query='')

        return urlunparse(parsed)

    except Exception as e:
        logger.warning(f"Fehler bei URL-Kanonisierung {url}: {e}")
        return url


# EXTRACTION VERSIONING
EXTRACTION_VERSION = "v1"

# Import PAGE_SET_VERSION and functions from the parallel persistence.py module
# We need to import from parent's persistence.py, not this package
import sys
import os

# Add parent directory to path temporarily to import persistence.py
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

try:
    # Pre-load required dependencies for persistence.py
    from .. import url_utils  # Import from parent (services.url_utils)

    # Load the standalone persistence.py
    _persistence_file = os.path.join(os.path.dirname(__file__), '..', 'persistence.py')
    if os.path.exists(_persistence_file):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_persistence_standalone", _persistence_file)
        if spec and spec.loader:
            _pers_standalone = importlib.util.module_from_spec(spec)

            # Manually set parent package to allow relative imports
            _pers_standalone.__package__ = 'services'

            # Ensure url_utils is available in sys.modules
            if 'services.url_utils' not in sys.modules:
                sys.modules['services.url_utils'] = url_utils

            spec.loader.exec_module(_pers_standalone)

            PAGE_SET_VERSION = getattr(_pers_standalone, 'PAGE_SET_VERSION', 'v1')
            create_deterministic_page_set = _pers_standalone.create_deterministic_page_set
            update_snapshot_status = _pers_standalone.update_snapshot_status
            increment_snapshot_progress = _pers_standalone.increment_snapshot_progress
            get_snapshot_page_count = _pers_standalone.get_snapshot_page_count
            check_page_set_changed = _pers_standalone.check_page_set_changed
            get_snapshot_change_counts = _pers_standalone.get_snapshot_change_counts
            update_snapshot_page_count = _pers_standalone.update_snapshot_page_count
        else:
            raise ImportError("Could not load persistence.py")
    else:
        raise ImportError("persistence.py not found")

except Exception as e:
    # Log error for debugging
    logger.error(f"Failed to load persistence.py functions: {e}")

    # Fallback
    PAGE_SET_VERSION = "v1"
    def create_deterministic_page_set(*args, **kwargs):
        raise NotImplementedError("Function not available from persistence.py")
    update_snapshot_status = create_deterministic_page_set
    increment_snapshot_progress = create_deterministic_page_set
    get_snapshot_page_count = create_deterministic_page_set
    check_page_set_changed = create_deterministic_page_set
    get_snapshot_change_counts = create_deterministic_page_set
    update_snapshot_page_count = create_deterministic_page_set

__all__ = [
    'Store',
    'get_store',
    'SQLiteStore',
    'SupabaseStore',
    'extract_text_from_html',
    'calculate_text_hash',
    'canonicalize_url',
    'EXTRACTION_VERSION',
    'PAGE_SET_VERSION',
    'create_deterministic_page_set',
    'update_snapshot_status',
    'increment_snapshot_progress',
    'get_snapshot_page_count',
    'check_page_set_changed',
    'get_snapshot_change_counts',
    'update_snapshot_page_count'
]
