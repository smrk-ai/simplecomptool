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
load_dotenv(dotenv_path=str(env_path))

# CORS-Konfiguration aus Environment-Variable
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

from services.crawler import (
    discover_urls, fetch_url, 
    get_playwright_usage_count, reset_playwright_usage_count,
    MAX_URLS, MAX_CONCURRENT_FETCHES
)
from services.persistence import (
    init_db, get_or_create_competitor, create_snapshot, save_page,
    update_snapshot_page_count, get_snapshot_pages, get_competitor_socials,
    create_profile_with_llm
)

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

# Pydantic Models
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

class ScanResponse(BaseModel):
    ok: bool
    error: Optional[ErrorDetail] = None
    competitor_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    pages: Optional[List[PageInfo]] = None
    profile: Optional[str] = None

class Competitor(BaseModel):
    id: str
    name: Optional[str]
    base_url: str
    created_at: str

class Snapshot(BaseModel):
    id: str
    competitor_id: str
    created_at: str
    page_count: int
    notes: Optional[str] = None

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

# Helper-Funktion für Supabase-Verfügbarkeit
def _ensure_supabase():
    """Prüft Supabase-Verfügbarkeit und gibt Client zurück"""
    from services.persistence import supabase
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")
    return supabase

# Datenbank-Funktionen (vereinfacht, da jetzt in persistence.py)
def get_competitors() -> List[dict]:
    try:
        supabase = _ensure_supabase()
        result = supabase.table('competitors').select(
            'id, name, base_url, created_at'
        ).order('created_at', desc=True).execute()
        
        # Snapshots für jeden Competitor laden
        for competitor in result.data:
            competitor_id = competitor['id']
            competitor_base_url = competitor.get('base_url', '')
            
            # base_url als url für Frontend-Kompatibilität
            competitor['url'] = competitor_base_url
            
            # Snapshots laden
            snapshots_result = supabase.table('snapshots').select(
                'id, created_at, page_count, notes'
            ).eq('competitor_id', competitor_id).order('created_at', desc=True).execute()
            
            # base_url zu jedem Snapshot hinzufügen
            for snapshot in snapshots_result.data:
                snapshot['base_url'] = competitor_base_url
            
            competitor["snapshots"] = snapshots_result.data
        
        return result.data
    except Exception as e:
        logger.error(f"Fehler beim Laden der Competitors: {e}")
        return []

def get_competitor(competitor_id: str) -> Optional[dict]:
    try:
        supabase = _ensure_supabase()
        # Competitor laden
        competitor_result = supabase.table('competitors').select(
            'id, name, base_url, created_at'
        ).eq('id', competitor_id).execute()

        if not competitor_result.data:
            return None

        competitor = competitor_result.data[0]
        competitor["snapshots"] = []
        competitor["socials"] = get_competitor_socials(competitor_id)
        
        # base_url als url für Frontend-Kompatibilität
        competitor['url'] = competitor.get('base_url', '')

        # Snapshots für diesen Competitor laden
        snapshots_result = supabase.table('snapshots').select(
            'id, created_at, page_count, notes'
        ).eq('competitor_id', competitor_id).order('created_at', desc=True).execute()

        # base_url von Competitor zu jedem Snapshot hinzufügen
        competitor_base_url = competitor.get('base_url', '')
        for snapshot in snapshots_result.data:
            snapshot['base_url'] = competitor_base_url

        competitor["snapshots"] = snapshots_result.data
        return competitor
    except Exception as e:
        logger.error(f"Fehler beim Laden des Competitors: {e}")
        return None

def get_snapshot(snapshot_id: str) -> Optional[dict]:
    try:
        supabase = _ensure_supabase()
        # Snapshot laden
        snapshot_result = supabase.table('snapshots').select(
            'id, competitor_id, created_at, page_count, notes'
        ).eq('id', snapshot_id).execute()

        if not snapshot_result.data:
            return None

        snapshot = snapshot_result.data[0]

        # Pages mit text_preview laden
        pages = get_snapshot_pages(snapshot_id)
        for page in pages:
            # Download-URLs hinzufügen
            page['raw_download_url'] = f"/api/pages/{page['id']}/raw"
            page['text_download_url'] = f"/api/pages/{page['id']}/text"

            # Text-Preview aus Supabase Storage laden
            try:
                if page.get('text_path'):
                    response = supabase.storage.from_('txt-files').download(page['text_path'])
                    text_content = response.decode('utf-8')
                    page['text_preview'] = text_content[:300]  # Erste 300 Zeichen
                else:
                    page['text_preview'] = ""
            except Exception as e:
                logger.warning(f"Fehler beim Laden der Text-Preview für Page {page['id']}: {e}")
                page['text_preview'] = ""

        snapshot["pages"] = pages
        return snapshot
    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshots: {e}")
        return None

# Logger konfigurieren
logger = logging.getLogger(__name__)

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
    
    # Playwright-Usage-Counter zurücksetzen
    reset_playwright_usage_count()
    
    logger.info(f"[{scan_id}] Scan gestartet für URL: {request.url}")

    async def execute_scan():
        """Interne Scan-Logik"""
        competitor_id = None
        snapshot_id = None
        pages_info = []
        pages_data = []
        profile = None
        
        try:
            # 1. Competitor finden oder erstellen (upsert by base_url)
            competitor_id = get_or_create_competitor(request.url, request.name)
            logger.info(f"[{scan_id}] Competitor ID: {competitor_id}")

            # 2. URLs entdecken
            logger.info(f"[{scan_id}] Starte URL-Discovery...")
            urls_to_fetch = await discover_urls(request.url)
            discover_count = len(urls_to_fetch)
            logger.info(f"[{scan_id}] Discovery abgeschlossen: {discover_count} URLs gefunden")
            
            if not urls_to_fetch:
                return ScanResponse(
                    ok=False,
                    error=ErrorDetail(code="NO_URLS", message="Keine URLs zum Crawlen gefunden"),
                    competitor_id=competitor_id
                )

            # Limit auf MAX_URLS sicherstellen
            if len(urls_to_fetch) > MAX_URLS:
                urls_to_fetch = urls_to_fetch[:MAX_URLS]
                logger.warning(f"[{scan_id}] URLs auf {MAX_URLS} begrenzt")

            # 3. Snapshot erstellen
            snapshot_id = create_snapshot(competitor_id)
            logger.info(f"[{scan_id}] Snapshot erstellt: {snapshot_id}")

            # 4. Semaphore für Concurrency-Control
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
            fetch_success_count = 0
            fetch_error_count = 0

            async def fetch_and_save_page(url: str):
                """Fetcht eine URL und speichert sie (mit Semaphore)"""
                nonlocal fetch_success_count, fetch_error_count
                async with semaphore:  # Concurrency-Control
                    try:
                        # URL fetchen
                        fetch_result = await fetch_url(url)
                        fetch_result['original_url'] = url

                        # Page speichern (inkl. Dateien und Social Links)
                        page_info = save_page(snapshot_id, fetch_result, competitor_id)

                        if page_info:
                            fetch_success_count += 1
                            # Sammle volle Page-Daten für LLM
                            full_page_data = {
                                'url': url,
                                'title': page_info.get('title'),
                                'meta_description': page_info.get('meta_description'),
                                'text_path': page_info.get('text_path') if 'text_path' in page_info else None
                            }
                            return (full_page_data, PageInfo(**page_info))
                        return None
                    except Exception as e:
                        fetch_error_count += 1
                        logger.warning(f"[{scan_id}] Fehler beim Fetchen von {url}: {e}")
                        return None

            # Alle URLs parallel fetchen (mit Concurrency-Limit)
            logger.info(f"[{scan_id}] Starte Fetch von {len(urls_to_fetch)} URLs (max {MAX_CONCURRENT_FETCHES} parallel)...")
            results = await asyncio.gather(
                *[fetch_and_save_page(url) for url in urls_to_fetch],
                return_exceptions=True
            )

            # Ergebnisse verarbeiten
            for result in results:
                if result and not isinstance(result, Exception):
                    full_page_data, page_info = result
                    pages_data.append(full_page_data)
                    pages_info.append(page_info)

            playwright_usage = get_playwright_usage_count()
            logger.info(f"[{scan_id}] Fetch abgeschlossen: {fetch_success_count} erfolgreich, {fetch_error_count} fehlgeschlagen, {playwright_usage} Playwright-Aufrufe")

            # 5. Snapshot-Statistiken aktualisieren
            update_snapshot_page_count(snapshot_id)

            # 6. Optional: LLM-Profil erstellen
            if request.llm:
                try:
                    logger.info(f"[{scan_id}] Starte LLM-Profil-Erstellung...")
                    profile = await create_profile_with_llm(competitor_id, snapshot_id, pages_data)
                    if profile is None:
                        logger.warning(f"[{scan_id}] LLM-Profil konnte nicht erstellt werden")
                except Exception as e:
                    logger.error(f"[{scan_id}] Fehler bei LLM-Profil-Erstellung: {e}")

            elapsed_time = time.time() - start_time
            logger.info(f"[{scan_id}] Scan erfolgreich abgeschlossen in {elapsed_time:.2f}s")

            return ScanResponse(
                ok=True,
                competitor_id=competitor_id,
                snapshot_id=snapshot_id,
                pages=pages_info,
                profile=profile
            )

        except asyncio.TimeoutError:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] Scan-Timeout nach {elapsed_time:.2f}s")
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="TIMEOUT", message=f"Scan überschritt Zeitlimit von {GLOBAL_SCAN_TIMEOUT} Sekunden"),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id,
                pages=pages_info if pages_info else None
            )
        except HTTPException as e:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] HTTP-Fehler nach {elapsed_time:.2f}s: {e.detail}")
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="HTTP_ERROR", message=str(e.detail)),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id
            )
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"[{scan_id}] Unerwarteter Fehler nach {elapsed_time:.2f}s: {e}", exc_info=True)
            return ScanResponse(
                ok=False,
                error=ErrorDetail(code="INTERNAL_ERROR", message=str(e)),
                competitor_id=competitor_id,
                snapshot_id=snapshot_id
            )

    # Gesamtzeit-Limit: 60 Sekunden
    try:
        result = await asyncio.wait_for(execute_scan(), timeout=GLOBAL_SCAN_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        elapsed_time = time.time() - start_time
        logger.error(f"[{scan_id}] Scan-Timeout nach {elapsed_time:.2f}s (Gesamtzeit-Limit)")
        return ScanResponse(
            ok=False,
            error=ErrorDetail(code="TIMEOUT", message=f"Scan überschritt Gesamtzeit-Limit von {GLOBAL_SCAN_TIMEOUT} Sekunden")
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

@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot_endpoint(snapshot_id: str):
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot nicht gefunden")
    return snapshot

@app.get("/api/pages/{page_id}/raw")
async def download_page_raw(page_id: str):
    """HTML-Datei als Download bereitstellen"""
    from services.persistence import supabase

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase-Verbindung nicht verfügbar")

    try:
        # Page-Daten laden
        page_result = supabase.table('pages').select('raw_path, url').eq('id', page_id).execute()

        if not page_result.data:
            raise HTTPException(status_code=404, detail="Page nicht gefunden")

        page = page_result.data[0]
        raw_path = page['raw_path']

        # HTML-Datei aus Supabase Storage laden
        response = supabase.storage.from_('html-files').download(raw_path)
        html_content = response.decode('utf-8')

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

    except Exception as e:
        logger.error(f"Fehler beim Laden der HTML-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"HTML-Datei konnte nicht geladen werden: {str(e)}"
        )

@app.get("/api/pages/{page_id}/text")
async def download_page_text(page_id: str):
    """TXT-Datei als Download bereitstellen"""
    from services.persistence import supabase

    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase-Verbindung nicht verfügbar")

    try:
        # Page-Daten laden
        page_result = supabase.table('pages').select('text_path, url').eq('id', page_id).execute()

        if not page_result.data:
            raise HTTPException(status_code=404, detail="Page nicht gefunden")

        page = page_result.data[0]
        text_path = page['text_path']

        # TXT-Datei aus Supabase Storage laden
        response = supabase.storage.from_('txt-files').download(text_path)
        text_content = response.decode('utf-8')

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

    except Exception as e:
        logger.error(f"Fehler beim Laden der TXT-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"TXT-Datei konnte nicht geladen werden: {str(e)}"
        )

# Startup Event
@app.on_event("startup")
def startup_event():
    init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
