from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime
import asyncio
import uuid
import time
import logging
from dotenv import load_dotenv

# Environment Variables laden
import pathlib
env_path = pathlib.Path(__file__).parent.parent / ".env.local"
try:
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path))
except Exception:
    # .env.local Datei existiert nicht oder ist nicht lesbar - ignorieren
    pass

# CORS-Konfiguration aus Environment-Variable
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

from services.crawler import (
    discover_urls,
    prioritize_urls,
    MAX_URLS
)
from services.fetchers.fetch_manager import FetchManager
from services.persistence import (
    init_db, get_or_create_competitor, create_snapshot, save_page,
    update_snapshot_page_count, get_snapshot_pages, get_competitor_socials,
    create_profile_with_llm, update_snapshot_status, increment_snapshot_progress
)
from services.url_utils import normalize_input_url, validate_url_for_scanning

app = FastAPI(title="Simple CompTool Backend", version="1.0.0")

# CORS für Frontend-Zugriff
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # Konfigurierbar über CORS_ORIGINS Environment-Variable
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Datenbank-Pfad
DB_PATH = "data/app.db"
os.makedirs("data", exist_ok=True)

# Scan-Konfiguration aus Environment-Variablen
GLOBAL_SCAN_TIMEOUT = float(os.getenv("GLOBAL_SCAN_TIMEOUT", "60.0"))
PHASE_A_TIMEOUT = float(os.getenv("PHASE_A_TIMEOUT", "20.0"))  # Timeout für Phase A (Quick Result)

# Pydantic Models
class Progress(BaseModel):
    done: int
    total: int

class ScanRequest(BaseModel):
    name: Optional[str] = None
    url: str
    llm: bool = False

class PageInfo(BaseModel):
    id: str
    url: str
    status: int
    sha256_text: str
    title: Optional[str] = None
    meta_description: Optional[str] = None

class ErrorDetail(BaseModel):
    code: str
    message: str

class ScanStats(BaseModel):
    playwright_browser_started: bool
    httpx_pages_count: int
    playwright_pages_count: int

class ScanResponse(BaseModel):
    ok: bool
    error: Optional[ErrorDetail] = None
    competitor_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    pages: Optional[List[PageInfo]] = None
    profile: Optional[str] = None
    render_mode: Optional[str] = None
    stats: Optional[ScanStats] = None
    snapshot_status: Optional[str] = None
    progress: Optional[Progress] = None

class Competitor(BaseModel):
    id: str
    name: Optional[str]
    base_url: str
    created_at: str

class SnapshotStatus(BaseModel):
    snapshot_id: str
    status: str  # "queued" | "running" | "partial" | "done" | "failed"
    progress: Progress
    error: Optional[ErrorDetail] = None

class Snapshot(BaseModel):
    id: str
    competitor_id: str
    created_at: str
    page_count: int
    notes: Optional[str] = None
    status: str
    progress_pages_done: int
    progress_pages_total: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

class Page(BaseModel):
    id: str
    snapshot_id: str
    url: str
    final_url: str
    status: int
    fetched_at: str
    via: str
    content_type: Optional[str] = None
    raw_path: Optional[str] = None
    text_path: Optional[str] = None
    sha256_text: Optional[str] = None
    title: Optional[str] = None
    meta_description: Optional[str] = None

class Social(BaseModel):
    id: str
    competitor_id: str
    platform: str
    handle: str
    url: str
    discovered_at: str
    source_url: str

class Profile(BaseModel):
    id: str
    competitor_id: str
    snapshot_id: str
    created_at: str
    text: str

# Datenbank-Funktionen
def get_competitors() -> List[dict]:
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
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

def get_competitor(competitor_id: str) -> Optional[dict]:
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
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
            'socials': get_competitor_socials(competitor_id)
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

        return competitor
    except Exception as e:
        logger.error(f"Fehler beim Laden des Competitors: {e}")
        return None
    finally:
        conn.close()

def get_snapshot(snapshot_id: str, with_previews: bool = False, preview_limit: int = 10) -> Optional[dict]:
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Snapshot laden
        cursor.execute('''
            SELECT id, competitor_id, created_at, page_count, notes, status,
                   progress_pages_done, progress_pages_total, started_at, finished_at,
                   error_code, error_message
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
            'pages': []
        }

        # Pages laden
        pages = get_snapshot_pages(snapshot_id)
        for i, page in enumerate(pages):
            # Download-URLs hinzufügen
            page['raw_download_url'] = f"/api/pages/{page['id']}/raw"
            page['text_download_url'] = f"/api/pages/{page['id']}/text"

            # Text-Preview nur laden wenn gewünscht und innerhalb des Limits
            if with_previews and i < preview_limit:
                try:
                    if page.get('text_path'):
                        text_file_path = f"data/snapshots/{page['text_path']}"
                        with open(text_file_path, 'r', encoding='utf-8') as f:
                            text_content = f.read()
                        page['text_preview'] = text_content[:300]  # Erste 300 Zeichen
                    else:
                        page['text_preview'] = ""
                except Exception as e:
                    logger.warning(f"Fehler beim Laden der Text-Preview für Page {page['id']}: {e}")
                    page['text_preview'] = ""
            else:
                # Keine Preview laden - entferne das Feld oder lasse es weg
                pass  # page['text_preview'] wird nicht gesetzt

        snapshot["pages"] = pages
        return snapshot
    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshots: {e}")
        return None
    finally:
        conn.close()

# Logger konfigurieren
logger = logging.getLogger(__name__)


async def complete_scan_background(scan_id: str, snapshot_id: str, rest_urls: List[str],
                                  render_mode: str, competitor_id: str):
    """
    Phase B: Vervollständigt den Scan im Hintergrund

    Args:
        scan_id: ID für Logging
        snapshot_id: ID des Snapshots
        rest_urls: URLs die noch gefetcht werden müssen
        render_mode: Render-Mode für Fetch
        competitor_id: ID des Competitors
    """
    logger.info(f"[{scan_id}] PHASE B: Starte Background-Completion für {len(rest_urls)} URLs")

    try:
        # Neuen FetchManager für Phase B erstellen (mit garantiertem Ressourcen-Management)
        async with FetchManager() as fetch_manager:
            # Rest-URLs fetchen
            fetch_results, _ = await fetch_manager.fetch_urls(rest_urls, render_mode)
            logger.info(f"[{scan_id}] Phase B: {len(fetch_results)} Rest-URLs gefetcht")

        # Ergebnisse speichern
        saved_count = 0
        for fetch_result in fetch_results:
            try:
                # FetchResult in Dict-Format konvertieren für save_page()
                fetch_dict = {
                    'original_url': fetch_result.url,
                    'final_url': fetch_result.final_url,
                    'status': fetch_result.status,
                    'headers': fetch_result.headers,
                    'html': fetch_result.html,
                    'fetched_at': fetch_result.fetched_at,
                    'via': fetch_result.via,
                    'content_type': fetch_result.content_type
                }

                # Page speichern
                page_info = await save_page(snapshot_id, fetch_dict, competitor_id)
                if page_info:
                    saved_count += 1
                    # Progress erhöhen
                    await increment_snapshot_progress(snapshot_id)

            except Exception as e:
                logger.warning(f"[{scan_id}] Fehler beim Speichern von {fetch_result.url}: {e}")

        # Social Links extrahieren (global aus allen Seiten)
        try:
            extract_social_links_from_snapshot(snapshot_id, competitor_id)
        except Exception as e:
            logger.error(f"[{scan_id}] Fehler bei Social Link Extraktion: {e}")

        # Snapshot als fertig markieren
        await update_snapshot_status(snapshot_id, "done", finished_at=datetime.now().isoformat())
        await update_snapshot_page_count(snapshot_id)

        logger.info(f"[{scan_id}] PHASE B: Abgeschlossen - {saved_count} Seiten gespeichert, Status: done")

    except Exception as e:
        logger.error(f"[{scan_id}] PHASE B: Fataler Fehler: {e}")
        # Bei fatalem Fehler: Status auf failed setzen
        await update_snapshot_status(snapshot_id, "failed",
                                    error_code="BACKGROUND_ERROR",
                                    error_message=str(e))


def extract_social_links_from_snapshot(snapshot_id: str, competitor_id: str):
    """
    Extrahiert Social Links aus allen Seiten eines Snapshots

    Args:
        snapshot_id: ID des Snapshots
        competitor_id: ID des Competitors
    """
    from services.persistence import extract_social_links, save_social_links
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Alle Pages dieses Snapshots laden
        cursor.execute('SELECT url, raw_path FROM pages WHERE snapshot_id = ?', (snapshot_id,))

        all_social_links = []
        for row in cursor.fetchall():
            url, raw_path = row
            try:
                # HTML aus lokaler Datei laden
                html_file_path = f"data/snapshots/{raw_path}"
                with open(html_file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # Social Links extrahieren
                social_links = extract_social_links(html_content, url)
                all_social_links.extend(social_links)

            except Exception as e:
                logger.warning(f"Fehler beim Laden der HTML für Social Links: {e}")

        # Social Links deduplizieren und speichern
        if all_social_links:
            save_social_links(competitor_id, all_social_links, "snapshot-completion")
            logger.info(f"Social Links für Snapshot {snapshot_id} gespeichert: {len(all_social_links)}")

    except Exception as e:
        logger.error(f"Fehler bei Social Link Extraktion für Snapshot {snapshot_id}: {e}")
    finally:
        conn.close()

# API Endpoints
@app.post("/api/scan", response_model=ScanResponse)
async def scan_endpoint(request: ScanRequest):
    """
    Vollständiger Website-Scan mit Crawling und Persistenz
    Optional: LLM-basierte Profil-Erstellung

    Härtungsmaßnahmen:
    - Max 20 Seiten
    - Max 60 Sekunden Gesamtzeit
    - Max 5 parallele Fetches
    - Strukturierte Fehlerbehandlung
    """
    # Scan-ID generieren für Logging
    scan_id = str(uuid.uuid4())
    start_time = time.time()

    # URL normalisieren und validieren
    try:
        normalized_url = normalize_input_url(request.url)
        validate_url_for_scanning(normalized_url)
        logger.info(f"[{scan_id}] URL normalisiert: {request.url} -> {normalized_url}")
    except ValueError as e:
        logger.warning(f"[{scan_id}] Ungültige URL: {request.url} - {str(e)}")
        return ScanResponse(
            ok=False,
            error=ErrorDetail(code="INVALID_URL", message=str(e))
        )

    logger.info(f"[{scan_id}] Scan gestartet für URL: {normalized_url}")

    async def execute_scan():
        """Interne Scan-Logik - Phase A (Quick Result)"""
        competitor_id = None
        snapshot_id = None
        pages_info = []
        pages_data = []
        profile = None
        render_mode = None

        try:
            # 1. Competitor finden oder erstellen (upsert by base_url)
            competitor_id = await get_or_create_competitor(normalized_url, request.name)
            logger.info(f"[{scan_id}] Competitor ID: {competitor_id}")

            # 2. URLs entdecken
            logger.info(f"[{scan_id}] Starte URL-Discovery...")
            all_urls = await discover_urls(normalized_url)
            discover_count = len(all_urls)
            logger.info(f"[{scan_id}] Discovery abgeschlossen: {discover_count} URLs gefunden")

            if not all_urls:
                return ScanResponse(
                    ok=False,
                    error=ErrorDetail(code="NO_URLS", message="Keine URLs zum Crawlen gefunden"),
                    competitor_id=competitor_id,
                    render_mode="httpx"  # fallback
                )

            # Limit auf MAX_URLS sicherstellen
            if len(all_urls) > MAX_URLS:
                all_urls = all_urls[:MAX_URLS]
                logger.warning(f"[{scan_id}] URLs auf {MAX_URLS} begrenzt")

            # 3. URLs priorisieren (Top 3 vs Rest)
            top_3_urls, rest_urls = prioritize_urls(all_urls, normalized_url)
            logger.info(f"[{scan_id}] URLs priorisiert: {len(top_3_urls)} Top-URLs, {len(rest_urls)} Rest-URLs")

            # 4. Render-Mode entscheiden und alle Fetches durchführen
            async with FetchManager() as fetch_manager:
                logger.info(f"[{scan_id}] Entscheide Render-Mode...")
                render_mode = await fetch_manager.decide_render_mode(normalized_url)
                logger.info(f"[{scan_id}] Render-Mode entschieden: {render_mode}")

                # 5. Snapshot erstellen mit Total-Count
                snapshot_id = await create_snapshot(competitor_id, page_count=len(all_urls))
                await update_snapshot_status(snapshot_id, "running", progress_pages_total=len(all_urls))
                logger.info(f"[{scan_id}] Snapshot erstellt: {snapshot_id}")

                # 6. PHASE A: NUR Top 3 URLs fetchen
                logger.info(f"[{scan_id}] PHASE A: Fetche {len(top_3_urls)} Top-URLs...")
                top_fetch_results, _ = await fetch_manager.fetch_urls(top_3_urls, render_mode)

                # 7. Top-URLs speichern
                for fetch_result in top_fetch_results:
                    try:
                        # FetchResult in Dict-Format konvertieren für save_page()
                        fetch_dict = {
                            'original_url': fetch_result.url,
                            'final_url': fetch_result.final_url,
                            'status': fetch_result.status,
                            'headers': fetch_result.headers,
                            'html': fetch_result.html,
                            'fetched_at': fetch_result.fetched_at,
                            'via': fetch_result.via,
                            'content_type': fetch_result.content_type
                        }

                        # Page speichern
                        page_info = await save_page(snapshot_id, fetch_dict, competitor_id)

                        if page_info:
                            # Sammle Page-Daten für LLM
                            full_page_data = {
                                'url': fetch_result.url,
                                'title': page_info.get('title'),
                                'meta_description': page_info.get('meta_description'),
                                'text_path': page_info.get('text_path') if 'text_path' in page_info else None
                            }
                            pages_data.append(full_page_data)
                            pages_info.append(PageInfo(**page_info))

                            # Progress erhöhen
                            await increment_snapshot_progress(snapshot_id)

                    except Exception as e:
                        logger.warning(f"[{scan_id}] Fehler beim Speichern von {fetch_result.url}: {e}")

                logger.info(f"[{scan_id}] Phase A abgeschlossen: {len(pages_info)} Seiten gespeichert")

                # 8. Optional: LLM-Profil erstellen (nur aus Top-Seiten)
                if request.llm and pages_data:
                    try:
                        logger.info(f"[{scan_id}] Erstelle LLM-Profil aus Top-Seiten...")
                        profile = await create_profile_with_llm(competitor_id, snapshot_id, pages_data)
                        logger.info(f"[{scan_id}] LLM-Profil erfolgreich erstellt")
                    except Exception as e:
                        logger.error(f"[{scan_id}] Fehler bei LLM-Profil-Erstellung: {e}")
                        profile = None  # Bei Fehler kein Profil setzen

                # 9. Status auf "partial" setzen
                await update_snapshot_status(snapshot_id, "partial")
                logger.info(f"[{scan_id}] Phase A abgeschlossen, Status: partial")

                # 10. PHASE B starten (asynchron, kein await!)
                if rest_urls:
                    asyncio.create_task(complete_scan_background(
                        scan_id=scan_id,
                        snapshot_id=snapshot_id,
                        rest_urls=rest_urls,
                        render_mode=render_mode,
                        competitor_id=competitor_id
                    ))
                    logger.info(f"[{scan_id}] Phase B im Hintergrund gestartet für {len(rest_urls)} Rest-URLs")

                elapsed_time = time.time() - start_time
                logger.info(f"[{scan_id}] Phase A abgeschlossen in {elapsed_time:.2f}s")

                return ScanResponse(
                    ok=True,
                    competitor_id=competitor_id,
                    snapshot_id=snapshot_id,
                    pages=pages_info,
                    profile=profile,
                    render_mode=render_mode,
                    snapshot_status="partial",
                    progress=Progress(done=len(pages_info), total=len(all_urls))
                )

        except asyncio.TimeoutError:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] Phase A Timeout nach {elapsed_time:.2f}s")
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="TIMEOUT", message=f"Phase A überschritt Zeitlimit von {PHASE_A_TIMEOUT} Sekunden"),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id,
                pages=pages_info if pages_info else None,
                render_mode=render_mode
            )
        except HTTPException as e:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] HTTP-Fehler nach {elapsed_time:.2f}s: {e.detail}")
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="HTTP_ERROR", message=str(e.detail)),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id,
                render_mode=render_mode
            )
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] Unerwarteter Fehler nach {elapsed_time:.2f}s: {e}", exc_info=True)
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="INTERNAL_ERROR", message=str(e)),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id,
                render_mode=render_mode
            )

    # Phase A Timeout: 20 Sekunden (sollte schnell sein)
    try:
        result = await asyncio.wait_for(execute_scan(), timeout=PHASE_A_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        elapsed_time = time.time() - start_time
        logger.error(f"[{scan_id}] Phase A Timeout nach {elapsed_time:.2f}s (Limit: {PHASE_A_TIMEOUT}s)")
        return ScanResponse(
            ok=False,
            error=ErrorDetail(code="TIMEOUT", message=f"Phase A überschritt Zeitlimit von {PHASE_A_TIMEOUT} Sekunden. Bitte versuchen Sie es erneut oder prüfen Sie die URL.")
        )

@app.get("/api/competitors")
def get_competitors_endpoint():
    return get_competitors()

@app.get("/api/competitors/{competitor_id}")
def get_competitor_endpoint(competitor_id: str):
    competitor = get_competitor(competitor_id)
    if not competitor:
        raise HTTPException(status_code=404, detail="Competitor nicht gefunden")
    return competitor

@app.get("/api/snapshots/{snapshot_id}/status")
def get_snapshot_status_endpoint(snapshot_id: str):
    """Gibt den aktuellen Status eines Snapshots zurück"""
    from services.persistence import get_snapshot_status

    status_data = get_snapshot_status(snapshot_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Snapshot nicht gefunden")

    return status_data


@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot_endpoint(snapshot_id: str, with_previews: bool = False, preview_limit: int = 10):
    """
    Holt einen Snapshot mit allen Seiten.

    Query-Parameter:
    - with_previews: Wenn true, werden Text-Previews für die ersten preview_limit Seiten geladen
    - preview_limit: Maximale Anzahl von Seiten mit Previews (default: 10)
    """
    snapshot = get_snapshot(snapshot_id, with_previews=with_previews, preview_limit=preview_limit)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot nicht gefunden")
    return snapshot

@app.get("/api/pages/{page_id}/raw")
async def download_page_raw(page_id: str):
    """HTML-Datei als Download bereitstellen"""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Page-Daten laden
        cursor.execute('SELECT raw_path, url FROM pages WHERE id = ?', (page_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Page nicht gefunden")

        raw_path, url = row

        # HTML-Datei aus lokalem Storage laden
        html_file_path = f"data/snapshots/{raw_path}"
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Als Download zurückgeben
        filename = f"{page_id}.html"
        return Response(
            content=html_content,
            media_type="text/html",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/html; charset=utf-8"
            }
        )

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="HTML-Datei nicht gefunden")
    except Exception as e:
        logger.error(f"Fehler beim Laden der HTML-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"HTML-Datei konnte nicht geladen werden: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/pages/{page_id}/text")
async def download_page_text(page_id: str):
    """TXT-Datei als Download bereitstellen"""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Page-Daten laden
        cursor.execute('SELECT text_path, url FROM pages WHERE id = ?', (page_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Page nicht gefunden")

        text_path, url = row

        # TXT-Datei aus lokalem Storage laden
        text_file_path = f"data/snapshots/{text_path}"
        with open(text_file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()

        # Als Download zurückgeben
        filename = f"{page_id}.txt"
        return Response(
            content=text_content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/plain; charset=utf-8"
            }
        )

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="TXT-Datei nicht gefunden")
    except Exception as e:
        logger.error(f"Fehler beim Laden der TXT-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"TXT-Datei konnte nicht geladen werden: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/pages/{page_id}/preview")
async def get_page_preview(page_id: str):
    """Gibt eine Text-Preview für eine einzelne Seite zurück (300 Zeichen)"""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Page-Daten laden
        cursor.execute('SELECT text_path, url FROM pages WHERE id = ?', (page_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Page nicht gefunden")

        text_path, url = row

        # Text-Preview aus lokaler Datei laden
        text_file_path = f"data/snapshots/{text_path}"
        with open(text_file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()

        return {
            'page_id': page_id,
            'text_preview': text_content[:300],  # Erste 300 Zeichen
            'has_more': len(text_content) > 300
        }

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Text-Datei nicht gefunden")
    except Exception as e:
        logger.error(f"Fehler beim Laden der Text-Preview für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Text-Preview konnte nicht geladen werden: {str(e)}"
        )
    finally:
        conn.close()

# Startup Event
@app.on_event("startup")
def startup_event():
    init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
