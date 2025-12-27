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
# Nur laden wenn Datei existiert (lokal), in Production nutzt Railway eigene Env-Vars
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))
else:
    load_dotenv()  # Lädt aus System-Environment

# CORS-Konfiguration aus Environment-Variable mit Security-Validierung
def _get_cors_origins() -> List[str]:
    """
    SECURITY FIX: Validiert CORS Origins und verhindert Wildcard-Missbrauch.

    Wildcard (*) ist gefährlich, da jede Website dann API-Requests machen kann.
    Dies öffnet CSRF-Angriffsvektoren.
    """
    origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]

    # Security Check: Wildcard blockieren
    if "*" in origins:
        logger.warning("⚠️  CORS Wildcard (*) detected in CORS_ORIGINS - SECURITY RISK!")
        logger.warning("⚠️  Falling back to localhost only for security")
        return ["http://localhost:3000"]

    # Validierung: Alle Origins müssen gültige URLs sein
    valid_origins = []
    for origin in origins:
        if origin.startswith("http://") or origin.startswith("https://"):
            valid_origins.append(origin)
        else:
            logger.warning(f"⚠️  Invalid CORS origin (must start with http:// or https://): {origin}")

    if not valid_origins:
        logger.warning("⚠️  No valid CORS origins found, using localhost")
        return ["http://localhost:3000"]

    logger.info(f"✅ CORS Origins configured: {', '.join(valid_origins)}")
    return valid_origins

CORS_ORIGINS = _get_cors_origins()

from services.crawler import (
    discover_urls, fetch_url, fetch_page_smart,
    get_playwright_usage_count, reset_playwright_usage_count,
    MAX_URLS, MAX_CONCURRENT_FETCHES
)
from services.persistence import (
    init_db, get_or_create_competitor, create_snapshot, save_page,
    update_snapshot_page_count, get_snapshot_pages, get_competitor_socials,
    create_profile_with_llm, extract_text_from_html_v2,
    get_previous_snapshot_map, calculate_text_hash
)
from utils.url_utils import canonicalize_url

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

# Health Check Endpoints für Railway
@app.get("/health/ready")
async def health_ready():
    """Health check endpoint for Railway"""
    return {"status": "ready", "timestamp": datetime.now().isoformat()}

@app.get("/health/live")
async def health_live():
    """Liveness check endpoint"""
    return {"status": "alive", "timestamp": datetime.now().isoformat()}

# Scan-Konfiguration aus Environment-Variablen
GLOBAL_SCAN_TIMEOUT = float(os.getenv("GLOBAL_SCAN_TIMEOUT", "60.0"))

# Pydantic Models
class ScanRequest(BaseModel):
    name: Optional[str] = None
    url: str
    llm: bool = False
    use_playwright: bool = False  # ✅ NEU: User-Toggle

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

        # Snapshots für diesen Competitor laden
        snapshots_result = supabase.table('snapshots').select(
            'id, created_at, page_count, notes'
        ).eq('competitor_id', competitor_id).order('created_at', desc=True).execute()

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

            # 3. Previous Snapshot für Hash-Comparison laden (VOR create_snapshot!)
            prev_map = await get_previous_snapshot_map(competitor_id)
            logger.info(f"[{scan_id}] Previous snapshot has {len(prev_map)} pages")

            # 4. Snapshot erstellen (NACH dem Laden des previous snapshots)
            snapshot_id = create_snapshot(competitor_id)
            logger.info(f"[{scan_id}] Snapshot erstellt: {snapshot_id}")

            # 5. Semaphore für Concurrency-Control
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
            fetch_success_count = 0
            fetch_error_count = 0

            async def fetch_and_save_page(url: str):
                """Fetcht eine URL und speichert sie (mit Semaphore)"""
                nonlocal fetch_success_count, fetch_error_count
                logger.info(f"[{scan_id}] Processing URL: {url} (type: {type(url).__name__})")
                async with semaphore:  # Concurrency-Control
                    try:
                        # ✅ Ensure URL is string
                        url_str = url if isinstance(url, str) else str(url)
                        # ✅ Nutze Smart Fetch
                        fetch_result = await fetch_page_smart(
                            url_str,
                            force_playwright=request.use_playwright
                        )

                        html = fetch_result['html']
                        via = fetch_result['via']
                        duration = fetch_result['duration']

                        # ✅ Extract mit V2 (vollständiger Content, kein 50k Limit!)
                        # PERFORMANCE FIX: Nur einmal extrahieren, dann an save_page() übergeben
                        extraction_result = extract_text_from_html_v2(html)
                        text = extraction_result['text']
                        text_length = extraction_result['text_length']
                        extraction_version = extraction_result['extraction_version']
                        has_truncation = extraction_result['has_truncation']

                        sha256_new = calculate_text_hash(text)
                        canonical = canonicalize_url(url)

                        # ✅ Hash-Vergleich mit Previous Snapshot
                        changed = True
                        prev_page_id = None

                        if canonical in prev_map:
                            prev_page = prev_map[canonical]
                            sha256_old = prev_page['sha256_text']

                            if sha256_new == sha256_old:
                                # UNCHANGED!
                                changed = False
                                prev_page_id = prev_page['page_id']
                                logger.info(f"[{scan_id}] ✓ UNCHANGED: {canonical}")
                            else:
                                # CHANGED!
                                prev_page_id = prev_page['page_id']
                                logger.info(f"[{scan_id}] ✗ CHANGED: {canonical}")
                        else:
                            # NEW PAGE!
                            logger.info(f"[{scan_id}] ➕ NEW: {canonical}")

                        # Extract title & meta (bleibt gleich wie vorher)
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        title = soup.find('title')
                        title_text = title.get_text(strip=True) if title else None

                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        meta_description = meta_desc.get('content', '').strip() if meta_desc else None

                        # Konvertiere zu altem fetch_url Format für save_page Kompatibilität (mit neuen Feldern)
                        # PERFORMANCE FIX: Text & Hash bereits extrahiert, als Parameter übergeben
                        fetch_result_compat = {
                            'final_url': fetch_result['url'],
                            'status': 200,  # Smart fetch gibt keinen Status zurück
                            'headers': {},
                            'html': fetch_result['html'],
                            'fetched_at': datetime.now().isoformat(),
                            'via': fetch_result['via'],
                            'original_url': url,
                            # NEUE FELDER FÜR CHANGE DETECTION
                            'canonical_url': canonical,
                            'changed': changed,
                            'prev_page_id': prev_page_id,
                            'text_length': text_length,
                            'normalized_len': len(text),
                            'has_truncation': has_truncation,
                            'extraction_version': extraction_version,
                            'fetch_duration': duration,
                            # PERFORMANCE FIX: Pre-extracted text & hash
                            '_extracted_text': text,
                            '_sha256_text': sha256_new
                        }

                        # Page speichern (inkl. Dateien und Social Links)
                        page_info = save_page(snapshot_id, fetch_result_compat, competitor_id)

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
async def get_snapshot_details(snapshot_id: str):
    """
    Liefert vollständige Snapshot-Details für Results Page.

    Response:
    - Snapshot Metadata
    - Competitor Info
    - All Pages (mit changed/unchanged Flag)
    - Profil (falls vorhanden)
    - Social Links
    - Stats (changed/unchanged counts)
    """
    try:
        supabase = _ensure_supabase()
        # Snapshot + Competitor laden
        snapshot_result = supabase.table("snapshots")\
            .select("*, competitors(*)")\
            .eq("id", snapshot_id)\
            .single()\
            .execute()

        if not snapshot_result.data:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        snapshot = snapshot_result.data
        competitor = snapshot.get('competitors')

        if not competitor:
            raise HTTPException(status_code=404, detail="Competitor not found")

        # Pages laden (alle, sortiert nach URL)
        pages_result = supabase.table("pages")\
            .select("id, url, canonical_url, changed, status, title, via, text_length, extraction_version")\
            .eq("snapshot_id", snapshot_id)\
            .order("canonical_url")\
            .execute()

        pages = pages_result.data or []

        # Stats berechnen
        changed_count = sum(1 for p in pages if p.get('changed', True))
        unchanged_count = len(pages) - changed_count

        # Profil laden (falls vorhanden)
        profile_result = supabase.table("profiles")\
            .select("text")\
            .eq("snapshot_id", snapshot_id)\
            .execute()

        # Profil ist optional - kann leer sein
        if profile_result.data and len(profile_result.data) > 0:
            profile_text = profile_result.data[0].get('text')
        else:
            profile_text = None

        # Social Links laden
        socials_result = supabase.table("socials")\
            .select("platform, url, handle")\
            .eq("competitor_id", competitor['id'])\
            .execute()

        # Response zusammenstellen
        return {
            "id": snapshot_id,
            "competitor_id": competitor['id'],
            "competitor_name": competitor.get('name') or competitor['base_url'],
            "competitor_url": competitor['base_url'],
            "created_at": snapshot['created_at'],
            "status": snapshot.get('status', 'done'),
            "pages": pages,
            "profile": profile_text,
            "socials": socials_result.data or [],
            "stats": {
                "total_pages": len(pages),
                "changed_pages": changed_count,
                "unchanged_pages": unchanged_count
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading snapshot {snapshot_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/pages/{page_id}/raw")
async def download_raw(page_id: str):
    """Download raw HTML - mit lokalem Fallback"""
    try:
        supabase = _ensure_supabase()

        page_result = supabase.table("pages")\
            .select("raw_path")\
            .eq("id", page_id)\
            .single()\
            .execute()

        if not page_result.data:
            raise HTTPException(status_code=404, detail="Page not found")

        raw_path = page_result.data.get('raw_path')

        if not raw_path:
            raise HTTPException(status_code=404, detail="Raw HTML not available")

        # Erst lokales Filesystem versuchen (Fallback für alte Daten)
        local_path = os.path.join("backend/data/snapshots", raw_path)
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return Response(content=content, media_type="text/html; charset=utf-8")

        # Ansonsten aus Supabase Storage laden
        try:
            file_data = supabase.storage.from_("snapshots").download(raw_path)
            return Response(content=file_data, media_type="text/html; charset=utf-8")
        except Exception as storage_error:
            logger.error(f"Supabase Storage download failed: {storage_error}")
            raise HTTPException(status_code=404, detail="File not found in storage")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download raw failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pages/{page_id}/text")
async def download_text(page_id: str):
    """Download extracted text - mit lokalem Fallback"""
    try:
        supabase = _ensure_supabase()

        page_result = supabase.table("pages")\
            .select("text_path")\
            .eq("id", page_id)\
            .single()\
            .execute()

        if not page_result.data:
            raise HTTPException(status_code=404, detail="Page not found")

        text_path = page_result.data.get('text_path')

        if not text_path:
            raise HTTPException(status_code=404, detail="Text not available")

        # Erst lokales Filesystem versuchen (Fallback für alte Daten)
        local_path = os.path.join("backend/data/snapshots", text_path)
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return Response(content=content, media_type="text/plain; charset=utf-8")

        # Ansonsten aus Supabase Storage laden
        try:
            file_data = supabase.storage.from_("snapshots").download(text_path)
            return Response(content=file_data, media_type="text/plain; charset=utf-8")
        except Exception as storage_error:
            logger.error(f"Supabase Storage download failed: {storage_error}")
            raise HTTPException(status_code=404, detail="File not found in storage")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download text failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Startup Event
@app.on_event("startup")
def startup_event():
    """Initialisiert Datenbank beim Server-Start"""
    init_db()
    logger.info("✅ Application started")

# Shutdown Event - CRITICAL FIX: Browser-Ressourcen freigeben
@app.on_event("shutdown")
async def shutdown_event():
    """
    Cleanup beim Server-Shutdown.

    CRITICAL FIX: Verhindert Memory Leak durch Zombie-Chromium-Prozesse.
    Ohne diesen Event bleibt der Browser-Prozess nach jedem Server-Restart aktiv.
    """
    from services.browser_manager import browser_manager
    try:
        await browser_manager.close()
        logger.info("✅ Browser closed successfully")
    except Exception as e:
        logger.error(f"❌ Error closing browser: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
