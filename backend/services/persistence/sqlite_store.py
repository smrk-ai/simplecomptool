"""
SQLite Store Implementation

Local persistence using SQLite database and file system storage.
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from .base import Store

logger = logging.getLogger(__name__)


class SQLiteStore(Store):
    """
    SQLite-based persistence store with local file storage.
    """

    def __init__(self, db_path: str = "data/app.db"):
        self.db_path = db_path
        self.db_write_lock = asyncio.Lock()

    async def init(self) -> None:
        """Initialize SQLite database and create tables."""
        os.makedirs("data", exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # SQLite PRAGMAs für bessere Concurrency und Performance
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")

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

        # Snapshots Tabelle - ERWEITERT
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
                extraction_version TEXT,
                page_set_version TEXT,
                page_set_hash TEXT,
                page_set_changed BOOLEAN DEFAULT FALSE,
                page_set_json JSON,
                FOREIGN KEY (competitor_id) REFERENCES competitors (id)
            )
        ''')

        # Pages Tabelle - ERWEITERT
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
                canonical_url TEXT NOT NULL,
                changed BOOLEAN NOT NULL DEFAULT TRUE,
                prev_page_id TEXT,
                normalized_len INTEGER,
                extraction_version TEXT DEFAULT 'v1' NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots (id)
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(canonical_url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_snapshot_canonical ON pages(snapshot_id, canonical_url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_socials_competitor_id ON socials(competitor_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_profiles_competitor_id ON profiles(competitor_id)')

        conn.commit()
        conn.close()

        logger.info("SQLite-Datenbank initialisiert")

    async def _execute_write_with_retry(self, operation_func, *args, max_retries=3):
        """Execute write operation with lock and retry logic."""
        async with self.db_write_lock:
            for attempt in range(max_retries):
                try:
                    return await operation_func(*args)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e).lower():
                        if attempt < max_retries - 1:
                            wait_time = 1 * (2 ** attempt)
                            logger.warning(f"DB locked, retry {attempt + 1}/{max_retries} after {wait_time}s: {e}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"DB locked nach {max_retries} Versuchen, gebe auf: {e}")
                            raise
                    else:
                        raise
                except Exception as e:
                    logger.error(f"Unerwarteter DB-Fehler: {e}")
                    raise

    async def upsert_competitor(self, name: Optional[str], base_url: str) -> str:
        """Create or update competitor by base_url."""
        async def _do_upsert():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                # Suche existierenden Competitor
                cursor.execute('SELECT id FROM competitors WHERE base_url = ?', (base_url,))
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
                    ''', (competitor_id, name, base_url, datetime.now().isoformat()))
                    conn.commit()
                    logger.info(f"Neuer Competitor erstellt: {competitor_id}")
                    return competitor_id

            except Exception as e:
                logger.error(f"Fehler bei Competitor-Operation: {e}")
                raise
            finally:
                conn.close()

        return await self._execute_write_with_retry(_do_upsert)

    async def create_snapshot(self, competitor_id: str, page_set_json: Dict[str, Any],
                            page_set_hash: str, progress_total: int,
                            extraction_version: str, page_set_version: str) -> str:
        """Create a new snapshot."""
        snapshot_id = str(uuid.uuid4())

        async def _do_create():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                cursor.execute('''
                    INSERT INTO snapshots (id, competitor_id, created_at, page_count, status,
                                         progress_pages_done, progress_pages_total, started_at,
                                         extraction_version, page_set_version, page_set_hash, page_set_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (snapshot_id, competitor_id, datetime.now().isoformat(), progress_total, 'queued',
                      0, progress_total, datetime.now().isoformat(),
                      extraction_version, page_set_version, page_set_hash, json.dumps(page_set_json)))

                conn.commit()
                logger.info(f"Snapshot erstellt: {snapshot_id}")
                return snapshot_id
            except Exception as e:
                logger.error(f"Fehler beim Erstellen des Snapshots: {e}")
                raise
            finally:
                conn.close()

        return await self._execute_write_with_retry(_do_create)

    async def update_snapshot_status(self, snapshot_id: str, status: str,
                                   progress_done: Optional[int] = None,
                                   progress_total: Optional[int] = None,
                                   error_code: Optional[str] = None,
                                   error_message: Optional[str] = None,
                                   finished_at: Optional[datetime] = None) -> None:
        """Update snapshot status."""
        async def _do_update():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                update_fields = ['status = ?']
                values = [status]

                if progress_done is not None:
                    update_fields.append('progress_pages_done = ?')
                    values.append(progress_done)

                if progress_total is not None:
                    update_fields.append('progress_pages_total = ?')
                    values.append(progress_total)

                if error_code is not None:
                    update_fields.append('error_code = ?')
                    values.append(error_code)

                if error_message is not None:
                    update_fields.append('error_message = ?')
                    values.append(error_message)

                if finished_at is not None:
                    update_fields.append('finished_at = ?')
                    values.append(finished_at.isoformat())

                values.append(snapshot_id)

                query = f"UPDATE snapshots SET {', '.join(update_fields)} WHERE id = ?"
                cursor.execute(query, values)
                conn.commit()

                logger.debug(f"Snapshot {snapshot_id} Status aktualisiert: {status}")
            except Exception as e:
                logger.error(f"Fehler beim Aktualisieren des Snapshot-Status: {e}")
                raise
            finally:
                conn.close()

        await self._execute_write_with_retry(_do_update)

    async def insert_or_update_page(self, snapshot_id: str, page_payload: Dict[str, Any]) -> str:
        """Insert or update a page."""
        page_id = str(uuid.uuid4())

        async def _do_insert():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                cursor.execute('''
                    INSERT INTO pages (id, snapshot_id, url, final_url, status, fetched_at, via,
                                     content_type, raw_path, text_path, sha256_text, title, meta_description,
                                     canonical_url, changed, prev_page_id, normalized_len, extraction_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    page_id, snapshot_id,
                    page_payload['url'], page_payload['final_url'], page_payload['status'],
                    page_payload['fetched_at'], page_payload['via'],
                    page_payload.get('content_type'), page_payload.get('raw_path'), page_payload.get('text_path'),
                    page_payload['sha256_text'], page_payload.get('title'), page_payload.get('meta_description'),
                    page_payload['canonical_url'], page_payload['changed'],
                    page_payload.get('prev_page_id'), page_payload.get('normalized_len'),
                    page_payload['extraction_version']
                ))

                conn.commit()
                logger.debug(f"Page gespeichert: {page_id}")
                return page_id

            except Exception as e:
                logger.error(f"Fehler beim Speichern der Page {page_id}: {e}")
                raise
            finally:
                conn.close()

        return await self._execute_write_with_retry(_do_insert)

    async def upsert_socials(self, competitor_id: str, socials: List[Dict[str, Any]]) -> None:
        """Insert or update social media links."""
        if not socials:
            return

        async def _do_upsert():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                for social in socials:
                    try:
                        cursor.execute('''
                            INSERT OR REPLACE INTO socials (id, competitor_id, platform, handle, url, discovered_at, source_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            str(uuid.uuid4()), competitor_id, social['platform'],
                            social['handle'], social['url'], datetime.now().isoformat(), social.get('source_url', '')
                        ))
                    except Exception as e:
                        logger.warning(f"Fehler beim Speichern von Social Link {social}: {e}")
                        continue

                conn.commit()
                logger.debug(f"{len(socials)} Social Links für Competitor {competitor_id} gespeichert")

            except Exception as e:
                logger.error(f"Fehler beim Speichern der Social Links: {e}")
                raise
            finally:
                conn.close()

        await self._execute_write_with_retry(_do_upsert)

    async def save_profile(self, competitor_id: str, snapshot_id: str, text: str) -> None:
        """Save or update a competitor profile."""
        async def _do_save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                cursor.execute('''
                    INSERT INTO profiles (id, competitor_id, snapshot_id, created_at, text)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(competitor_id, snapshot_id) DO UPDATE SET
                        text = excluded.text,
                        created_at = excluded.created_at
                ''', (str(uuid.uuid4()), competitor_id, snapshot_id, datetime.now().isoformat(), text))

                conn.commit()
                logger.info(f"Profil für Competitor {competitor_id} erstellt/aktualisiert")

            except Exception as e:
                logger.error(f"Fehler bei Profil-Speicherung: {e}")
                raise
            finally:
                conn.close()

        await self._execute_write_with_retry(_do_save)

    async def get_latest_snapshot_id(self, competitor_id: str) -> Optional[str]:
        """Get the most recent snapshot ID for a competitor."""
        async def _do_get():
            conn = sqlite3.connect(self.db_path)
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

        return await self._execute_write_with_retry(_do_get)

    async def get_pages_map(self, snapshot_id: str) -> Dict[str, Dict[str, Any]]:
        """Get a map of canonical_url -> page data for change detection."""
        async def _do_get():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                cursor.execute('''
                    SELECT id, canonical_url, sha256_text, text_path, raw_path
                    FROM pages WHERE snapshot_id = ?
                ''', (snapshot_id,))

                page_map = {}
                for row in cursor.fetchall():
                    page_id, canonical_url, sha256_text, text_path, raw_path = row
                    page_map[canonical_url] = {
                        'page_id': page_id,
                        'sha256_text': sha256_text,
                        'text_path': text_path,
                        'raw_path': raw_path
                    }

                return page_map

            except Exception as e:
                logger.error(f"Fehler beim Laden der Page-Map: {e}")
                return {}
            finally:
                conn.close()

        return await self._execute_write_with_retry(_do_get)

    async def get_snapshot(self, snapshot_id: str, with_previews: bool = False,
                          preview_limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get complete snapshot data including pages."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Snapshot laden
            cursor.execute('''
                SELECT id, competitor_id, created_at, page_count, notes, status,
                       progress_pages_done, progress_pages_total, started_at, finished_at,
                       error_code, error_message, extraction_version, page_set_version,
                       page_set_hash, page_set_changed, page_set_json
                FROM snapshots WHERE id = ?
            ''', (snapshot_id,))

            row = cursor.fetchone()
            if not row:
                return None

            snapshot = {
                'id': row[0],
                'competitor_id': row[1],
                'created_at': row[2],
                'page_count': row[3],
                'notes': row[4],
                'status': row[5],
                'progress_pages_done': row[6],
                'progress_pages_total': row[7],
                'started_at': row[8],
                'finished_at': row[9],
                'error_code': row[10],
                'error_message': row[11],
                'extraction_version': row[12],
                'page_set_version': row[13],
                'page_set_hash': row[14],
                'page_set_changed': bool(row[15]),
                'page_set_json': json.loads(row[16]) if row[16] else None,
                'pages': []
            }

            # Pages laden
            cursor.execute('''
                SELECT id, url, final_url, status, fetched_at, via, content_type,
                       raw_path, text_path, sha256_text, title, meta_description,
                       canonical_url, changed, prev_page_id
                FROM pages WHERE snapshot_id = ? ORDER BY fetched_at
            ''', (snapshot_id,))

            pages = []
            for row in cursor.fetchall():
                page = {
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
                    'prev_page_id': row[14],
                    'raw_download_url': f"/api/pages/{row[0]}/raw",
                    'text_download_url': f"/api/pages/{row[0]}/text"
                }

                # Text-Preview nur laden wenn gewünscht und innerhalb des Limits
                if with_previews and len(pages) < preview_limit:
                    try:
                        if page.get('text_path'):
                            text_file_path = f"data/snapshots/{page['text_path']}"
                            with open(text_file_path, 'r', encoding='utf-8') as f:
                                text_content = f.read()
                            page['text_preview'] = text_content[:300]
                        else:
                            page['text_preview'] = ""
                    except Exception as e:
                        logger.warning(f"Fehler beim Laden der Text-Preview für Page {page['id']}: {e}")
                        page['text_preview'] = ""

                pages.append(page)

            snapshot['pages'] = pages
            return snapshot

        except Exception as e:
            logger.error(f"Fehler beim Laden des Snapshots: {e}")
            return None
        finally:
            conn.close()

    async def list_competitors(self) -> List[Dict[str, Any]]:
        """Get all competitors with their snapshots."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Competitors laden
            cursor.execute('SELECT id, name, base_url, created_at FROM competitors ORDER BY created_at DESC')
            competitors = []

            for row in cursor.fetchall():
                competitor = {
                    'id': row[0],
                    'name': row[1],
                    'base_url': row[2],
                    'created_at': row[3],
                    'url': row[2],  # base_url als url für Frontend-Kompatibilität
                    'snapshots': []
                }

                # Snapshots für diesen Competitor laden
                cursor.execute('''
                    SELECT id, created_at, page_count, notes, status, progress_pages_done, progress_pages_total
                    FROM snapshots WHERE competitor_id = ? ORDER BY created_at DESC
                ''', (row[0],))

                competitor['snapshots'] = [
                    {
                        'id': srow[0],
                        'created_at': srow[1],
                        'page_count': srow[2],
                        'notes': srow[3],
                        'status': srow[4],
                        'progress_pages_done': srow[5],
                        'progress_pages_total': srow[6],
                        'base_url': row[2]  # base_url hinzufügen
                    }
                    for srow in cursor.fetchall()
                ]

                competitors.append(competitor)

            return competitors
        except Exception as e:
            logger.error(f"Fehler beim Laden der Competitors: {e}")
            return []
        finally:
            conn.close()

    async def get_competitor(self, competitor_id: str) -> Optional[Dict[str, Any]]:
        """Get a single competitor with snapshots and socials."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Competitor laden
            cursor.execute('SELECT id, name, base_url, created_at FROM competitors WHERE id = ?', (competitor_id,))
            row = cursor.fetchone()

            if not row:
                return None

            competitor = {
                'id': row[0],
                'name': row[1],
                'base_url': row[2],
                'created_at': row[3],
                'url': row[2],  # base_url als url für Frontend-Kompatibilität
                'snapshots': [],
                'socials': []
            }

            # Snapshots für diesen Competitor laden
            cursor.execute('''
                SELECT id, created_at, page_count, notes
                FROM snapshots WHERE competitor_id = ? ORDER BY created_at DESC
            ''', (competitor_id,))

            competitor['snapshots'] = [
                {
                    'id': srow[0],
                    'created_at': srow[1],
                    'page_count': srow[2],
                    'notes': srow[3],
                    'base_url': row[2]  # base_url hinzufügen
                }
                for srow in cursor.fetchall()
            ]

            # Socials laden
            cursor.execute('''
                SELECT platform, handle, url, discovered_at, source_url
                FROM socials WHERE competitor_id = ?
            ''', (competitor_id,))

            competitor['socials'] = [
                {
                    'platform': row[0],
                    'handle': row[1],
                    'url': row[2],
                    'discovered_at': row[3],
                    'source_url': row[4]
                }
                for row in cursor.fetchall()
            ]

            return competitor

        except Exception as e:
            logger.error(f"Fehler beim Laden des Competitors: {e}")
            return None
        finally:
            conn.close()

    async def download_page_raw(self, page_id: str) -> Optional[bytes]:
        """Download raw HTML content for a page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Page-Daten laden
            cursor.execute('SELECT raw_path FROM pages WHERE id = ?', (page_id,))
            row = cursor.fetchone()

            if not row or not row[0]:
                return None

            raw_path = row[0]

            # HTML-Datei aus lokalem Storage laden
            html_file_path = f"data/snapshots/{raw_path}"
            with open(html_file_path, 'rb') as f:
                return f.read()

        except Exception as e:
            logger.error(f"Fehler beim Laden der HTML-Datei für Page {page_id}: {e}")
            return None
        finally:
            conn.close()

    async def download_page_text(self, page_id: str) -> Optional[bytes]:
        """Download normalized text content for a page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Page-Daten laden
            cursor.execute('SELECT text_path FROM pages WHERE id = ?', (page_id,))
            row = cursor.fetchone()

            if not row or not row[0]:
                return None

            text_path = row[0]

            # TXT-Datei aus lokalem Storage laden
            text_file_path = f"data/snapshots/{text_path}"
            with open(text_file_path, 'rb') as f:
                return f.read()

        except Exception as e:
            logger.error(f"Fehler beim Laden der TXT-Datei für Page {page_id}: {e}")
            return None
        finally:
            conn.close()

    async def get_page_preview(self, page_id: str, max_length: int = 300) -> Optional[Dict[str, Any]]:
        """Get text preview for a page."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Page-Daten laden
            cursor.execute('SELECT text_path FROM pages WHERE id = ?', (page_id,))
            row = cursor.fetchone()

            if not row or not row[0]:
                return None

            text_path = row[0]

            # Text-Preview aus lokaler Datei laden
            text_file_path = f"data/snapshots/{text_path}"
            with open(text_file_path, 'r', encoding='utf-8') as f:
                text_content = f.read()

            return {
                'page_id': page_id,
                'text_preview': text_content[:max_length],
                'has_more': len(text_content) > max_length
            }

        except Exception as e:
            logger.error(f"Fehler beim Laden der Text-Preview für Page {page_id}: {e}")
            return None
        finally:
            conn.close()
