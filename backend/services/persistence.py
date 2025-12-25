import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
import openai
import asyncio
import hashlib
import json

from .url_utils import normalize_input_url

# EXTRACTION VERSIONING
EXTRACTION_VERSION = "v1"

# PAGE-SET VERSIONING
PAGE_SET_VERSION = "v1"

# PAGE-SET KONSTANTEN
MAX_PAGES = 20
PAGE_SET_RULES = {
    "max_pages": MAX_PAGES,
    "allow_subdomains": True,
    "excluded_keywords": ["privacy", "terms", "login", "logout", "admin", "wp-admin"],
    "ranking_weights": {
        "priority_keywords": ["pricing", "plan", "product", "features", "solutions", "customers", "case-study", "docs", "blog", "changelog", "news", "careers", "jobs", "about", "company", "team", "security"],
        "path_depth_penalty": 0.1,  # Weniger tief verschachtelte Pfade bevorzugen
        "home_page_boost": 2.0     # Homepage boost
    }
}


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
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
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


def calculate_page_set_hash(page_set: Dict) -> str:
    """Berechnet SHA256 Hash des Page-Sets für Determinismus-Verifikation"""
    # JSON serialisieren und hashen (sort_keys=True für Determinismus)
    page_set_json = json.dumps(page_set, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(page_set_json.encode('utf-8')).hexdigest()


def create_deterministic_page_set(discovered_urls: List[str], base_url: str) -> Dict:
    """
    ERSTELLT EIN DETERMINISTISCHES PAGE-SET ARTEFAKT (REGEL 2)

    Args:
        discovered_urls: Roh-URLs von discover_urls()
        base_url: Normalisierte Basis-URL

    Returns:
        Page-Set Dict mit version, rules, urls und hash
    """
    from urllib.parse import urlparse

    # 1. URLs normalisieren und deduplizieren
    normalized_urls = set()
    for url in discovered_urls:
        normalized = normalize_input_url(url)
        if normalized:
            normalized_urls.add(normalized)

    # 2. URLs nach Ranking sortieren (deterministisch)
    def calculate_ranking_score(url: str) -> float:
        """Berechnet Ranking-Score für deterministische Sortierung"""
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')

        score = 0.0

        # Home page boost
        if path in ['', '/']:
            score += PAGE_SET_RULES["ranking_weights"]["home_page_boost"]

        # Priority keywords boost
        path_lower = path.lower()
        for keyword in PAGE_SET_RULES["ranking_weights"]["priority_keywords"]:
            if keyword in path_lower:
                score += 1.0

        # Path depth penalty (kürzere Pfade bevorzugen)
        path_parts = [p for p in path.split('/') if p]
        depth_penalty = len(path_parts) * PAGE_SET_RULES["ranking_weights"]["path_depth_penalty"]
        score -= depth_penalty

        # Lexikographische Sortierung als Tie-Breaker für Determinismus
        score = score * 1000 + (1.0 / (1.0 + len(url)))  # Kleine Variation für Sortierung

        return score

    # Sortiere URLs nach Score (höchste zuerst), dann lexikographisch
    ranked_urls = sorted(normalized_urls,
                        key=lambda u: (-calculate_ranking_score(u), u))

    # 3. Auf MAX_PAGES begrenzen
    final_urls = ranked_urls[:MAX_PAGES]

    # 4. Page-Set Artefakt erstellen
    page_set = {
        "page_set_version": PAGE_SET_VERSION,
        "rules": PAGE_SET_RULES,
        "urls": final_urls,
        "created_at": datetime.now().isoformat(),
        "base_url": base_url
    }

    # 5. Hash berechnen
    page_set_hash = calculate_page_set_hash(page_set)
    page_set["page_set_hash"] = page_set_hash

    logger.info(f"Page-Set erstellt: {len(final_urls)} URLs, Hash: {page_set_hash[:16]}...")

    return page_set

# Globaler Lock für alle SQLite Write-Operationen
DB_WRITE_LOCK = asyncio.Lock()


async def _execute_write_with_retry(operation_func, *args, max_retries=3):
    """
    Führt eine Write-Operation mit Lock und Retry-Logik aus.

    Args:
        operation_func: Funktion die die DB-Operation ausführt
        *args: Argumente für die Operation
        max_retries: Maximale Anzahl von Retry-Versuchen

    Returns:
        Ergebnis der Operation

    Raises:
        Exception: Wenn alle Retries fehlschlagen
    """
    async with DB_WRITE_LOCK:
        for attempt in range(max_retries):
            try:
                return await operation_func(*args)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    if attempt < max_retries - 1:
                        wait_time = 1 * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"DB locked, retry {attempt + 1}/{max_retries} after {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"DB locked nach {max_retries} Versuchen, gebe auf: {e}")
                        raise
                else:
                    # Andere OperationalError - nicht retry
                    raise
            except Exception as e:
                # Andere Fehler - nicht retry
                logger.error(f"Unerwarteter DB-Fehler: {e}")
                raise

logger = logging.getLogger(__name__)

# SQLite Konfiguration
DB_PATH = "data/app.db"

# Maximale Text-Länge pro Seite
MAX_TEXT_LENGTH = 50000

# Social Media Plattformen und ihre Erkennungsmuster
SOCIAL_PLATFORMS = {
    'twitter': [
        r'twitter\.com/(\w+)',
        r'x\.com/(\w+)',
        r'https?://(?:www\.)?(?:twitter|x)\.com/(\w+)'
    ],
    'linkedin': [
        r'linkedin\.com/(?:in|company)/([\w-]+)',
        r'https?://(?:www\.)?linkedin\.com/(?:in|company)/([\w-]+)'
    ],
    'facebook': [
        r'facebook\.com/([\w.-]+)',
        r'https?://(?:www\.)?facebook\.com/([\w.-]+)'
    ],
    'instagram': [
        r'instagram\.com/(\w+)',
        r'https?://(?:www\.)?instagram\.com/(\w+)'
    ],
    'youtube': [
        r'youtube\.com/(?:user|c|channel)/([\w-]+)',
        r'https?://(?:www\.)?youtube\.com/(?:user|c|channel)/([\w-]+)'
    ],
    'tiktok': [
        r'tiktok\.com/@([\w.-]+)',
        r'https?://(?:www\.)?tiktok\.com/@([\w.-]+)'
    ],
    'github': [
        r'github\.com/(\w+)',
        r'https?://(?:www\.)?github\.com/(\w+)'
    ]
}


def init_db():
    """Initialisiert die SQLite-Datenbank und erstellt Tabellen falls nötig"""
    os.makedirs("data", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # SQLite PRAGMAs für bessere Concurrency und Performance
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")  # 5 Sekunden Timeout

    logger.info("SQLite PRAGMAs gesetzt: WAL mode, NORMAL sync, 5s busy timeout")

    # Competitors Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS competitors (
            id TEXT PRIMARY KEY,
            name TEXT,
            base_url TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
    ''')

    # Snapshots Tabelle - ERWEITERT um Page-Set Metadaten
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            competitor_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            page_count INTEGER DEFAULT 0,
            notes TEXT,
            status TEXT DEFAULT 'queued',
            progress_pages_done INTEGER DEFAULT 0,
            progress_pages_total INTEGER DEFAULT 0,
            started_at TEXT,
            finished_at TEXT,
            error_code TEXT,
            error_message TEXT,
            -- NEUE FELDER für Guards
            extraction_version TEXT,
            page_set_version TEXT,
            page_set_hash TEXT,
            page_set_changed BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        )
    ''')

    # MIGRATION: Neue Spalten zu bestehenden Snapshots hinzufügen
    try:
        cursor.execute("ALTER TABLE snapshots ADD COLUMN extraction_version TEXT")
        logger.info("Migration: extraction_version Spalte hinzugefügt")
    except sqlite3.OperationalError:
        # Spalte existiert bereits
        pass

    try:
        cursor.execute("ALTER TABLE snapshots ADD COLUMN page_set_version TEXT")
        logger.info("Migration: page_set_version Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE snapshots ADD COLUMN page_set_hash TEXT")
        logger.info("Migration: page_set_hash Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE snapshots ADD COLUMN page_set_changed BOOLEAN DEFAULT FALSE")
        logger.info("Migration: page_set_changed Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    # MIGRATION: Neue Spalten zu bestehenden Pages hinzufügen
    try:
        cursor.execute("ALTER TABLE pages ADD COLUMN canonical_url TEXT NOT NULL DEFAULT ''")
        logger.info("Migration: canonical_url Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE pages ADD COLUMN changed BOOLEAN NOT NULL DEFAULT TRUE")
        logger.info("Migration: changed Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE pages ADD COLUMN prev_page_id TEXT")
        logger.info("Migration: prev_page_id Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE pages ADD COLUMN normalized_len INTEGER")
        logger.info("Migration: normalized_len Spalte hinzugefügt")
    except sqlite3.OperationalError:
        pass

    # Pages Tabelle - ERWEITERT um Change Detection
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            url TEXT NOT NULL,
            final_url TEXT NOT NULL,
            status INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            via TEXT NOT NULL,
            content_type TEXT,
            raw_path TEXT,
            text_path TEXT,
            sha256_text TEXT,
            title TEXT,
            meta_description TEXT,
            -- NEUE FELDER für Change Detection
            canonical_url TEXT NOT NULL,
            changed BOOLEAN NOT NULL DEFAULT TRUE,
            prev_page_id TEXT,
            normalized_len INTEGER,
            FOREIGN KEY (snapshot_id) REFERENCES snapshots (id),
            FOREIGN KEY (prev_page_id) REFERENCES pages (id)
        )
    ''')

    # Socials Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS socials (
            id TEXT PRIMARY KEY,
            competitor_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            handle TEXT NOT NULL,
            url TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            UNIQUE(competitor_id, platform, handle),
            FOREIGN KEY (competitor_id) REFERENCES competitors (id)
        )
    ''')

    # Profiles Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            competitor_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY (competitor_id) REFERENCES competitors (id),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots (id),
            UNIQUE(competitor_id, snapshot_id)
        )
    ''')

    # Indizes für Performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_id ON snapshots(competitor_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_snapshot_id ON pages(snapshot_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_socials_competitor_id ON socials(competitor_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_competitor_id ON profiles(competitor_id)')

    # Indizes für Change Detection (nach Migration)
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(canonical_url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_snapshot_canonical ON pages(snapshot_id, canonical_url)')
    except sqlite3.OperationalError as e:
        logger.warning(f"Index-Erstellung übersprungen (Migration läuft): {e}")

    conn.commit()
    conn.close()

    logger.info("SQLite-Datenbank initialisiert und migriert")


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


def extract_social_links(html: str, base_url: str) -> List[Dict]:
    """
    Extrahiert Social Media Links aus HTML

    Returns:
        Liste von Dicts mit platform, handle, url
    """
    social_links = []

    try:
        soup = BeautifulSoup(html, 'lxml')

        # Finde alle Links
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)

            for platform, patterns in SOCIAL_PLATFORMS.items():
                for pattern in patterns:
                    match = re.search(pattern, full_url, re.IGNORECASE)
                    if match:
                        handle = match.group(1)
                        social_links.append({
                            'platform': platform,
                            'handle': handle,
                            'url': full_url
                        })
                        break  # Nur ersten Match pro URL verwenden

    except Exception as e:
        logger.warning(f"Fehler bei Social Link Extraktion: {e}")

    return social_links


async def get_or_create_competitor(base_url: str, name: Optional[str] = None) -> str:
    """Holt oder erstellt einen Competitor anhand der base_url"""
    # Normalisiere base_url zu kanonischer Form
    normalized_base_url = normalize_input_url(base_url)

    async def _do_competitor_operation():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Suche existierenden Competitor
            cursor.execute('SELECT id FROM competitors WHERE base_url = ?', (normalized_base_url,))
            result = cursor.fetchone()

            if result:
                competitor_id = result[0]
                logger.debug(f"Existierender Competitor gefunden: {competitor_id}")
                return competitor_id
            else:
                # Erstelle neuen Competitor
                competitor_id = str(uuid.uuid4())
                cursor.execute('''
                    INSERT INTO competitors (id, name, base_url, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (competitor_id, name, normalized_base_url, datetime.now().isoformat()))
                conn.commit()
                logger.info(f"Neuer Competitor erstellt: {competitor_id}")
                return competitor_id

        except Exception as e:
            logger.error(f"Fehler bei Competitor-Operation: {e}")
            raise
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_competitor_operation)


async def create_snapshot(competitor_id: str, page_count: int = 0, notes: Optional[str] = None,
                        page_set: Optional[Dict] = None) -> str:
    """Erstellt einen neuen Snapshot mit erweiterten Metadaten"""
    snapshot_id = str(uuid.uuid4())

    # Page-Set Metadaten extrahieren (falls vorhanden)
    page_set_version = page_set.get("page_set_version") if page_set else None
    page_set_hash = page_set.get("page_set_hash") if page_set else None
    extraction_version = EXTRACTION_VERSION

    async def _do_create_snapshot():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO snapshots (id, competitor_id, created_at, page_count, notes, status,
                                     progress_pages_done, progress_pages_total, started_at,
                                     extraction_version, page_set_version, page_set_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (snapshot_id, competitor_id, datetime.now().isoformat(), page_count, notes, 'queued',
                  0, page_count, datetime.now().isoformat(),
                  extraction_version, page_set_version, page_set_hash))

            conn.commit()
            logger.info(f"Snapshot erstellt: {snapshot_id} (extraction_v={extraction_version}, page_set_v={page_set_version})")
            return snapshot_id
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Snapshots: {e}")
            raise
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_create_snapshot)


async def check_page_set_changed(competitor_id: str, new_page_set_hash: str) -> bool:
    """
    Prüft, ob sich das Page-Set seit dem letzten Snapshot geändert hat

    Returns:
        True wenn sich das Page-Set geändert hat, False sonst
    """
    async def _do_check():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Hole den neuesten erfolgreichen Snapshot für diesen Competitor
            cursor.execute('''
                SELECT page_set_hash FROM snapshots
                WHERE competitor_id = ? AND status = 'done' AND page_set_hash IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            ''', (competitor_id,))

            row = cursor.fetchone()
            if row and row[0]:
                last_hash = row[0]
                changed = last_hash != new_page_set_hash
                if changed:
                    logger.info(f"Page-Set geändert für Competitor {competitor_id}: {last_hash[:16]}... -> {new_page_set_hash[:16]}...")
                return changed
            else:
                # Erster Snapshot - keine Änderung
                return False

        except Exception as e:
            logger.error(f"Fehler bei Page-Set Vergleich: {e}")
            return False
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_check)


async def mark_page_set_changed(snapshot_id: str, changed: bool = True):
    """Markiert einen Snapshot als 'page_set_changed'"""
    async def _do_mark():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE snapshots SET page_set_changed = ? WHERE id = ?
            ''', (changed, snapshot_id))
            conn.commit()

            if changed:
                logger.info(f"Snapshot {snapshot_id} als page_set_changed markiert")

        except Exception as e:
            logger.error(f"Fehler beim Markieren von page_set_changed: {e}")
            raise
        finally:
            conn.close()

    await _execute_write_with_retry(_do_mark)


async def find_previous_snapshot(competitor_id: str) -> Optional[str]:
    """
    Findet den neuesten erfolgreichen Snapshot für einen Competitor.

    Returns:
        snapshot_id des neuesten erfolgreichen Snapshots oder None
    """
    async def _do_find():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT id FROM snapshots
                WHERE competitor_id = ? AND status = 'done'
                ORDER BY created_at DESC LIMIT 1
            ''', (competitor_id,))

            row = cursor.fetchone()
            return row[0] if row else None

        except Exception as e:
            logger.error(f"Fehler beim Suchen des vorherigen Snapshots: {e}")
            return None
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_find)


async def load_previous_page_map(snapshot_id: str) -> Dict[str, Dict]:
    """
    Lädt eine Map von canonical_url -> Page-Daten für Change Detection.

    Returns:
        Dict[canonical_url, {
            'page_id': str,
            'sha256_text': str,
            'text_path': str,
            'raw_path': str,
            'title': str,
            'meta_description': str,
            'normalized_len': int
        }]
    """
    async def _do_load():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT id, canonical_url, sha256_text, text_path, raw_path, title, meta_description, normalized_len
                FROM pages WHERE snapshot_id = ?
            ''', (snapshot_id,))

            page_map = {}
            for row in cursor.fetchall():
                page_id, canonical_url, sha256_text, text_path, raw_path, title, meta_description, normalized_len = row
                page_map[canonical_url] = {
                    'page_id': page_id,
                    'sha256_text': sha256_text,
                    'text_path': text_path,
                    'raw_path': raw_path,
                    'title': title,
                    'meta_description': meta_description,
                    'normalized_len': normalized_len
                }

            logger.debug(f"Loaded {len(page_map)} pages from previous snapshot {snapshot_id}")
            return page_map

        except Exception as e:
            logger.error(f"Fehler beim Laden der vorherigen Page-Map: {e}")
            return {}
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_load)


async def get_snapshot_change_counts(snapshot_id: str) -> Dict[str, int]:
    """
    Berechnet Change-Counts für einen Snapshot.

    Returns:
        {
            'changed_pages_count': int,
            'unchanged_pages_count': int,
            'total_pages_count': int
        }
    """
    async def _do_count():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT changed, COUNT(*) as count
                FROM pages WHERE snapshot_id = ?
                GROUP BY changed
            ''', (snapshot_id,))

            counts = {'changed_pages_count': 0, 'unchanged_pages_count': 0, 'total_pages_count': 0}

            for row in cursor.fetchall():
                changed, count = row
                if changed:
                    counts['changed_pages_count'] = count
                else:
                    counts['unchanged_pages_count'] = count
                counts['total_pages_count'] += count

            return counts

        except Exception as e:
            logger.error(f"Fehler beim Berechnen der Change-Counts: {e}")
            return {'changed_pages_count': 0, 'unchanged_pages_count': 0, 'total_pages_count': 0}
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_count)


async def persist_page_snapshot(snapshot_id: str, fetch_result: Dict, competitor_id: str,
                       prev_page_map: Optional[Dict[str, Dict]] = None) -> Dict:
    """
    ZENTRALE PAGE-PERSISTENCE FUNKTION MIT GUARDS (REGEL 1) + HASH-GATE

    Speichert eine Page mit allen erforderlichen Komponenten:
    - raw_html (erforderlich)
    - normalized_text (erforderlich)
    - sha256 hash (erforderlich)
    - extraction_version (erforderlich)
    - canonical_url (neu)
    - changed/prev_page_id (neu für Change Detection)

    Args:
        snapshot_id: ID des neuen Snapshots
        fetch_result: Fetch-Ergebnis
        competitor_id: Competitor ID
        prev_page_map: Optional Map von canonical_url -> prev Page data für Hash-Gate

    Raises:
        ValueError: Wenn eine erforderliche Komponente fehlt
    """
    # REGEL 1 GUARDS: Validierung der erforderlichen Komponenten
    if not fetch_result.get('html'):
        raise ValueError("REGEL 1 VERLETZT: raw_html ist erforderlich aber fehlt")

    # Text-Extraktion (wie bisher)
    title, meta_description, normalized_text = extract_text_from_html(fetch_result['html'])

    if not normalized_text.strip():
        raise ValueError("REGEL 1 VERLETZT: normalized_text ist erforderlich aber leer")

    # SHA256 Hash berechnen
    sha256_text = calculate_text_hash(normalized_text)
    if not sha256_text:
        raise ValueError("REGEL 1 VERLETZT: sha256 hash konnte nicht berechnet werden")

    # Canonical URL erstellen
    canonical_url = canonicalize_url(fetch_result.get('final_url', fetch_result['url']))

    # HASH-GATE: Previous Page prüfen
    changed = True
    prev_page_id = None
    reuse_files = False

    if prev_page_map and canonical_url in prev_page_map:
        prev_page = prev_page_map[canonical_url]
        prev_sha256 = prev_page.get('sha256_text')

        if prev_sha256 and prev_sha256 == sha256_text:
            # UNVERÄNDERT: Hash-Gate aktiviert
            changed = False
            prev_page_id = prev_page['page_id']
            reuse_files = True
            logger.debug(f"Hash-Gate: Page {canonical_url} unverändert (SHA256 gleich)")

    # Extraction Version setzen
    extraction_version = EXTRACTION_VERSION

    # Guards bestanden - jetzt speichern
    return await _save_page_with_components(
        snapshot_id=snapshot_id,
        fetch_result=fetch_result,
        competitor_id=competitor_id,
        normalized_text=normalized_text,
        sha256_text=sha256_text,
        extraction_version=extraction_version,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        changed=changed,
        prev_page_id=prev_page_id,
        reuse_files=reuse_files,
        prev_page_data=prev_page_map.get(canonical_url) if prev_page_map and not changed else None
    )


async def _save_page_with_components(snapshot_id: str, fetch_result: Dict, competitor_id: str,
                                   normalized_text: str, sha256_text: str, extraction_version: str,
                                   title: str, meta_description: str, canonical_url: str, changed: bool,
                                   prev_page_id: Optional[str], reuse_files: bool,
                                   prev_page_data: Optional[Dict]) -> Dict:
    """
    Interne Funktion für das tatsächliche Speichern (nach Guards).
    """
    page_id = str(uuid.uuid4())

    # Lokale Dateipfade - mit File-Reuse für unveränderte Pages
    snapshot_dir = f"data/snapshots/{snapshot_id}/pages"
    os.makedirs(snapshot_dir, exist_ok=True)

    if reuse_files and prev_page_data:
        # FILE REUSE: Verwende Pfade der vorherigen Page (Hardlink oder Copy)
        html_path = prev_page_data.get('raw_path', f"{snapshot_id}/pages/{page_id}.html")
        txt_path = prev_page_data.get('text_path', f"{snapshot_id}/pages/{page_id}.txt")

        try:
            # Erstelle Hardlinks für File-Reuse (effizienter als Kopieren)
            old_html_path = f"data/snapshots/{html_path}"
            old_txt_path = f"data/snapshots/{txt_path}"

            new_html_path = f"data/snapshots/{snapshot_id}/pages/{page_id}.html"
            new_txt_path = f"data/snapshots/{snapshot_id}/pages/{page_id}.txt"

            # Hardlink versuchen, bei Fehler kopieren
            try:
                os.link(old_html_path, new_html_path)
                os.link(old_txt_path, new_txt_path)
                logger.debug(f"File-Reuse: Hardlinks erstellt für {canonical_url}")
            except OSError:
                # Fallback: Dateien kopieren
                import shutil
                shutil.copy2(old_html_path, new_html_path)
                shutil.copy2(old_txt_path, new_txt_path)
                logger.debug(f"File-Reuse: Dateien kopiert für {canonical_url}")

            html_path = f"{snapshot_id}/pages/{page_id}.html"
            txt_path = f"{snapshot_id}/pages/{page_id}.txt"

        except Exception as e:
            logger.warning(f"File-Reuse fehlgeschlagen für {canonical_url}, schreibe neue Dateien: {e}")
            reuse_files = False

    if not reuse_files:
        # NORMALE FILE-SPEICHERUNG
        html_path = f"{snapshot_id}/pages/{page_id}.html"
        txt_path = f"{snapshot_id}/pages/{page_id}.txt"

        try:
            # HTML-Datei lokal speichern
            html_file_path = f"data/snapshots/{html_path}"
            with open(html_file_path, 'w', encoding='utf-8') as f:
                f.write(fetch_result['html'])

            # TXT-Datei lokal speichern
            txt_file_path = f"data/snapshots/{txt_path}"
            with open(txt_file_path, 'w', encoding='utf-8') as f:
                f.write(normalized_text)

        except Exception as e:
            logger.error(f"Fehler beim Speichern der Dateien für Page {page_id}: {e}")
            return None

    # Content-Type ermitteln
    content_type = fetch_result.get('headers', {}).get('content-type', 'text/html')

    # Page-Daten für DB-Operation
    page_data = {
        'id': page_id,
        'snapshot_id': snapshot_id,
        'url': fetch_result.get('original_url', fetch_result['final_url']),
        'final_url': fetch_result['final_url'],
        'status': fetch_result['status'],
        'fetched_at': fetch_result['fetched_at'],
        'via': fetch_result['via'],
        'content_type': content_type,
        'html_path': html_path,
        'txt_path': txt_path,
        'sha256_text': sha256_text,
        'title': title,
        'meta_description': meta_description
    }

    async def _do_save_page():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO pages (id, snapshot_id, url, final_url, status, fetched_at, via, content_type, raw_path, text_path, sha256_text, title, meta_description, canonical_url, changed, prev_page_id, normalized_len)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                page_data['id'], page_data['snapshot_id'],
                page_data['url'], page_data['final_url'], page_data['status'],
                page_data['fetched_at'], page_data['via'],
                page_data['content_type'], page_data['html_path'], page_data['txt_path'],
                page_data['sha256_text'], page_data['title'], page_data['meta_description'],
                canonical_url, changed, prev_page_id, len(normalized_text)
            ))

            conn.commit()

            # Social Links extrahieren und speichern (auch async)
            social_links = extract_social_links(fetch_result['html'], fetch_result['final_url'])
            await save_social_links(competitor_id, social_links, fetch_result['final_url'])

            logger.debug(f"Page gespeichert: {page_id}")

            return {
                'id': page_id,
                'url': page_data['url'],
                'status': page_data['status'],
                'sha256_text': page_data['sha256_text'],
                'title': page_data['title'],
                'meta_description': page_data['meta_description'],
                'text_path': page_data['txt_path'],
                'canonical_url': canonical_url,
                'changed': changed,
                'prev_page_id': prev_page_id
            }

        except Exception as e:
            logger.error(f"Fehler beim Speichern der Page {page_id}: {e}")
            raise
        finally:
            conn.close()

    try:
        return await _execute_write_with_retry(_do_save_page)
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Page {page_id} nach Retry: {e}")
        return None


# LEGACY FUNKTION - VERWENDET JETZT persist_page_snapshot()
async def save_page(snapshot_id: str, fetch_result: Dict, competitor_id: str) -> Dict:
    """
    LEGACY WRAPPER - verwendet jetzt persist_page_snapshot() mit Guards

    Args:
        snapshot_id: ID des Snapshots
        fetch_result: Dict mit Fetch-Ergebnis
        competitor_id: ID des Competitors

    Returns:
        Dict mit Page-Daten für API Response
    """
    try:
        return await persist_page_snapshot(snapshot_id, fetch_result, competitor_id)
    except ValueError as e:
        logger.error(f"REGEL 1 GUARD VERLETZT beim Speichern von Page: {e}")
        # Bei Guard-Verletzung: Snapshot auf failed setzen
        await update_snapshot_status(snapshot_id, "failed",
                                   error_code="GUARD_VIOLATION",
                                   error_message=str(e))
        return None


async def save_social_links(competitor_id: str, social_links: List[Dict], source_url: str):
    """Speichert Social Media Links (unique per competitor/platform/handle)"""
    if not social_links:
        return

    async def _do_save_social_links():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            for social in social_links:
                try:
                    # SQLite upsert (INSERT OR REPLACE)
                    cursor.execute('''
                        INSERT OR REPLACE INTO socials (id, competitor_id, platform, handle, url, discovered_at, source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()), competitor_id, social['platform'],
                        social['handle'], social['url'], datetime.now().isoformat(), source_url
                    ))

                except Exception as e:
                    logger.warning(f"Fehler beim Speichern von Social Link {social}: {e}")
                    continue

            conn.commit()
            logger.debug(f"{len(social_links)} Social Links für Competitor {competitor_id} gespeichert")

        except Exception as e:
            logger.error(f"Fehler beim Speichern der Social Links: {e}")
            raise
        finally:
            conn.close()

    await _execute_write_with_retry(_do_save_social_links)


async def update_snapshot_page_count(snapshot_id: str):
    """Aktualisiert die page_count eines Snapshots"""

    async def _do_update_page_count():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Zähle Pages für diesen Snapshot
            cursor.execute('SELECT COUNT(*) FROM pages WHERE snapshot_id = ?', (snapshot_id,))
            count = cursor.fetchone()[0]

            # Aktualisiere Snapshot
            cursor.execute('UPDATE snapshots SET page_count = ? WHERE id = ?', (count, snapshot_id))
            conn.commit()

            logger.debug(f"Snapshot {snapshot_id} page_count auf {count} aktualisiert")

        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren der page_count: {e}")
            raise
        finally:
            conn.close()

    await _execute_write_with_retry(_do_update_page_count)


async def update_snapshot_status(snapshot_id: str, status: str, **kwargs):
    """
    Aktualisiert Status und andere Felder eines Snapshots

    Args:
        snapshot_id: ID des Snapshots
        status: Neuer Status ("queued", "running", "partial", "done", "failed")
        **kwargs: Zusätzliche Felder (progress_pages_done, progress_pages_total, finished_at, error_code, error_message)
    """

    async def _do_update_status():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Erstelle Update-Query dynamisch
            update_fields = ['status = ?']
            values = [status]

            allowed_fields = ['progress_pages_done', 'progress_pages_total', 'finished_at', 'error_code', 'error_message']
            for key, value in kwargs.items():
                if key in allowed_fields:
                    update_fields.append(f'{key} = ?')
                    values.append(value)

            values.append(snapshot_id)  # Für WHERE clause

            query = f"UPDATE snapshots SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()

            logger.debug(f"Snapshot {snapshot_id} Status aktualisiert: {status}")
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren des Snapshot-Status: {e}")
            raise
        finally:
            conn.close()

    await _execute_write_with_retry(_do_update_status)


def get_snapshot_status(snapshot_id: str) -> Optional[Dict]:
    """
    Holt Status-Informationen eines Snapshots

    Returns:
        Dict mit status, progress, error oder None wenn nicht gefunden
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT id, status, progress_pages_done, progress_pages_total, error_code, error_message
            FROM snapshots WHERE id = ?
        ''', (snapshot_id,))

        row = cursor.fetchone()
        if not row:
            return None

        # Erstelle Response-Dict
        status_data = {
            'snapshot_id': row[0],
            'status': row[1],
            'progress': {
                'done': row[2],
                'total': row[3]
            }
        }

        # Füge Error hinzu wenn vorhanden
        if row[4]:  # error_code
            status_data['error'] = {
                'code': row[4],
                'message': row[5] or ''  # error_message
            }

        return status_data

    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshot-Status: {e}")
        return None
    finally:
        conn.close()


async def increment_snapshot_progress(snapshot_id: str):
    """Erhöht progress_pages_done um 1"""

    async def _do_increment_progress():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            # Erhöhe progress_pages_done um 1
            cursor.execute('''
                UPDATE snapshots SET progress_pages_done = progress_pages_done + 1 WHERE id = ?
            ''', (snapshot_id,))
            conn.commit()

            logger.debug(f"Snapshot {snapshot_id} progress erhöht")

        except Exception as e:
            logger.error(f"Fehler beim Inkrementieren des Progress: {e}")
            raise
        finally:
            conn.close()

    await _execute_write_with_retry(_do_increment_progress)


def get_competitor_socials(competitor_id: str) -> List[Dict]:
    """Holt alle Social Media Accounts eines Competitors"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT platform, handle, url, discovered_at, source_url
            FROM socials WHERE competitor_id = ?
        ''', (competitor_id,))

        return [
            {
                'platform': row[0],
                'handle': row[1],
                'url': row[2],
                'discovered_at': row[3],
                'source_url': row[4]
            }
            for row in cursor.fetchall()
        ]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Social Links: {e}")
        return []
    finally:
        conn.close()


async def get_snapshot_page_count(snapshot_id: str) -> int:
    """Holt die aktuelle Page-Anzahl eines Snapshots"""
    async def _do_get_count():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT COUNT(*) FROM pages WHERE snapshot_id = ?', (snapshot_id,))
            count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"Fehler beim Zählen der Pages: {e}")
            return 0
        finally:
            conn.close()

    return await _execute_write_with_retry(_do_get_count)


def get_snapshot_pages(snapshot_id: str) -> List[Dict]:
    """Holt alle Pages eines Snapshots"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT id, url, final_url, status, fetched_at, via, content_type,
                   raw_path, text_path, sha256_text, title, meta_description,
                   canonical_url, changed, prev_page_id
            FROM pages WHERE snapshot_id = ? ORDER BY fetched_at
        ''', (snapshot_id,))

        return [
            {
                'id': row[0],
                'url': row[1],
                'final_url': row[2],
                'status': row[3],
                'fetched_at': row[4],
                'via': row[5],
                'content_type': row[6],
                'raw_path': row[7],
                'text_path': row[8],
                'sha256_text': row[9],
                'title': row[10],
                'meta_description': row[11],
                'canonical_url': row[12],
                'changed': bool(row[13]),
                'prev_page_id': row[14]
            }
            for row in cursor.fetchall()
        ]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Pages: {e}")
        return []
    finally:
        conn.close()


async def create_profile_with_llm(competitor_id: str, snapshot_id: str, pages: List[Dict]) -> str:
    """
    Erstellt ein Profil mit LLM basierend auf den gecrawlten Seiten

    Args:
        competitor_id: ID des Competitors
        snapshot_id: ID des Snapshots
        pages: Liste der gecrawlten Pages

    Returns:
        Profil-Text (immer verfügbar, da idempotent gespeichert)
    """
    try:
        # OpenAI API Key aus Environment
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY nicht gesetzt, überspringe Profil-Erstellung")
            # Erstelle trotzdem einen Eintrag mit Standard-Text
            profile_text = "LLM-Profil nicht verfügbar (API-Key fehlt)"

        # Filtere relevante Seiten (keine privacy/terms, sortiere nach Textlänge)
        relevant_pages = []
        for page in pages:
            url_path = urlparse(page['url']).path.lower()
            if not any(exclude in url_path for exclude in ['privacy', 'terms']):
                relevant_pages.append(page)

        # Sortiere nach Textlänge (wir nehmen an, dass längerer Text mehr Inhalt hat)
        # Da wir die Textlänge nicht direkt haben, verwenden wir eine Heuristik
        relevant_pages.sort(key=lambda p: len(p.get('title', '')) + len(p.get('meta_description', '')), reverse=True)

        # Nimm bis zu 3 Seiten mit höchstem Textumfang
        selected_pages = relevant_pages[:3]

        # Sammle Inhalte für LLM
        llm_input_parts = []

        # Füge Titel und Meta-Descriptions hinzu
        for page in selected_pages:
            if page.get('title'):
                llm_input_parts.append(f"Titel: {page['title']}")
            if page.get('meta_description'):
                llm_input_parts.append(f"Beschreibung: {page['meta_description']}")

            # Lade den normalisierten Text aus lokaler Datei (max 6000 chars pro Seite)
            if page.get('text_path'):
                try:
                    # Datei lokal laden
                    text_file_path = f"data/snapshots/{page['text_path']}"
                    with open(text_file_path, 'r', encoding='utf-8') as f:
                        text_content = f.read()[:6000]  # Max 6000 chars pro Seite
                    if text_content.strip():
                        llm_input_parts.append(f"Inhalt: {text_content}")
                except Exception as e:
                    logger.warning(f"Fehler beim Laden der Textdatei {page['text_path']}: {e}")

        # Füge Top URLs hinzu (max 10)
        all_urls = [page['url'] for page in pages[:10]]
        if all_urls:
            llm_input_parts.append(f"Wichtige URLs: {', '.join(all_urls)}")

        # Kombiniere Input
        full_input = "\n\n".join(llm_input_parts)

        if not full_input.strip():
            logger.warning("Kein Input für LLM verfügbar")
            return None

        # OpenAI Client
        client = openai.AsyncOpenAI(api_key=api_key)

        # System Message für deterministisches, kurzes Ergebnis
        system_message = """Du bist ein Analyst für Unternehmensprofile. Erstelle ein präzises Unternehmensprofil basierend auf den bereitgestellten Informationen. Schreibe maximal 5 Zeilen Fließtext auf Deutsch. Keine Überschrift, keine Aufzählung, kein "Think", keine Fragen. Fokussiere dich auf das Wesentliche: Was macht das Unternehmen, welche Zielgruppe, welche Besonderheiten."""

        # LLM Call
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": full_input}
            ],
            max_tokens=300,  # Begrenze Tokens für kurze Antwort
            temperature=0.3  # Niedrige Temperature für deterministische Antworten
        )

        profile_text = response.choices[0].message.content.strip()

        # Speichere Profil in SQLite Datenbank (idempotent)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # UPSERT: Insert or Update bei UNIQUE constraint violation
        cursor.execute('''
            INSERT INTO profiles (id, competitor_id, snapshot_id, created_at, text)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(competitor_id, snapshot_id) DO UPDATE SET
                text = excluded.text,
                created_at = excluded.created_at
        ''', (str(uuid.uuid4()), competitor_id, snapshot_id, datetime.now().isoformat(), profile_text))

        conn.commit()

        logger.info(f"Profil für Competitor {competitor_id} erstellt/aktualisiert")

        # Gib immer das gespeicherte Profil zurück (idempotent)
        cursor.execute('''
            SELECT text FROM profiles
            WHERE competitor_id = ? AND snapshot_id = ?
        ''', (competitor_id, snapshot_id))

        row = cursor.fetchone()
        if row:
            return row[0]  # Gib gespeicherten Text zurück
        else:
            logger.error(f"Profil konnte nicht abgerufen werden nach Speicherung")
            return profile_text  # Fallback

    except Exception as e:
        logger.error(f"Fehler bei LLM-Profil-Erstellung: {e}")
        return None
    finally:
        # Stelle sicher, dass die Verbindung geschlossen wird
        try:
            conn.close()
        except:
            pass


def get_competitor_profile(competitor_id: str, snapshot_id: Optional[str] = None) -> Optional[Dict]:
    """Holt das neueste Profil eines Competitors (oder für einen spezifischen Snapshot)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        if snapshot_id:
            cursor.execute('''
                SELECT id, snapshot_id, created_at, text
                FROM profiles
                WHERE competitor_id = ? AND snapshot_id = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (competitor_id, snapshot_id))
        else:
            cursor.execute('''
                SELECT id, snapshot_id, created_at, text
                FROM profiles
                WHERE competitor_id = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (competitor_id,))

        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'snapshot_id': row[1],
                'created_at': row[2],
                'text': row[3]
            }

        return None

    except Exception as e:
        logger.error(f"Fehler beim Laden des Profils: {e}")
        return None
    finally:
        conn.close()
