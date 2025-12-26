from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
import re
import ipaddress
from pydantic import Field, validator
from datetime import datetime
import asyncio
import uuid
import time
import logging
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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

# CORS-Validierung: allow_credentials=True ist nicht mit allow_origins=["*"] kompatibel
if "*" in CORS_ORIGINS:
    ALLOW_CREDENTIALS = False
else:
    ALLOW_CREDENTIALS = True

# Persistence Backend Konfiguration
PERSISTENCE_BACKEND = os.getenv("PERSISTENCE_BACKEND", "sqlite").lower()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "snapshots")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

# Validierung der Supabase-Konfiguration
if PERSISTENCE_BACKEND == "supabase":
    if not SUPABASE_URL:
        raise ValueError("PERSISTENCE_BACKEND=supabase erfordert SUPABASE_URL")
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("PERSISTENCE_BACKEND=supabase erfordert SUPABASE_SERVICE_ROLE_KEY")

from services.crawler import (
    discover_urls,
    prioritize_urls,
    MAX_URLS
)
from services.fetchers.fetch_manager import FetchManager
from services.persistence import (
    extract_text_from_html,
    calculate_text_hash,
    canonicalize_url,
    EXTRACTION_VERSION,
    PAGE_SET_VERSION,
    get_store,
    create_deterministic_page_set,
    update_snapshot_status,
    increment_snapshot_progress,
    get_snapshot_page_count,
    check_page_set_changed,
    get_snapshot_change_counts,
    update_snapshot_page_count
)
# Initialize the persistence store
store = get_store()
from services.url_utils import normalize_input_url, validate_url_for_scanning

# Background task tracking
_background_tasks: set = set()

# Rate Limiter initialisieren
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Simple CompTool Backend", version="1.0.0")

# Rate Limiter zu App hinzufügen
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS für Frontend-Zugriff
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # Konfigurierbar über CORS_ORIGINS Environment-Variable
    allow_credentials=ALLOW_CREDENTIALS,  # Automatisch False wenn CORS_ORIGINS="*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize store on startup
@app.on_event("startup")
async def initialize_store():
    await store.init()

@app.on_event("shutdown")
async def shutdown_background_tasks():
    """Cancel all background tasks on shutdown"""
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    logger.info("Background tasks cancelled")

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
    name: Optional[str] = Field(None, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)
    llm: bool = False

    @validator('url')
    def validate_url(cls, v):
        v = v.strip()

        # Längenprüfung
        if len(v) > 2048:
            raise ValueError('URL zu lang (max 2048 Zeichen)')

        if len(v) < 4:
            raise ValueError('URL zu kurz')

        # Wenn kein Schema, füge https:// hinzu für Validierung
        test_url = v if v.startswith(('http://', 'https://')) else f'https://{v}'

        # Grundlegende URL-Pattern-Prüfung
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S*)?$', re.IGNORECASE
        )

        if not url_pattern.match(test_url):
            raise ValueError('Ungültiges URL-Format')

        # SSRF-Schutz: Private IPs blocken
        from urllib.parse import urlparse
        parsed = urlparse(test_url)
        hostname = parsed.hostname

        if hostname:
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_reserved:
                    raise ValueError('Private/lokale IP-Adressen sind nicht erlaubt')
            except ValueError:
                pass  # Hostname ist kein IP - das ist OK

        return v

class PageInfo(BaseModel):
    id: str
    url: str
    status: int
    sha256_text: str
    title: Optional[str] = None
    meta_description: Optional[str] = None
    canonical_url: str
    changed: bool
    prev_page_id: Optional[str] = None

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
async def get_competitors() -> List[dict]:
    """Get all competitors with their snapshots."""
    try:
        return await store.list_competitors()
    except Exception as e:
        logger.error(f"Fehler beim Laden der Competitors: {e}")
        return []

async def get_competitor(competitor_id: str) -> Optional[dict]:
    """Get a single competitor with snapshots and socials."""
    try:
        return await store.get_competitor(competitor_id)
    except Exception as e:
        logger.error(f"Fehler beim Laden des Competitors: {e}")
        return None


async def persist_page_snapshot(snapshot_id: str, fetch_result: Dict, competitor_id: str,
                       prev_page_map: Optional[Dict[str, Dict]] = None) -> Dict:
    """
    ZENTRALE PAGE-PERSISTENCE FUNKTION MIT GUARDS (REGEL 1) + HASH-GATE

    Speichert eine Page mit allen erforderlichen Komponenten über Store-Interface.
    """
    # REGEL 1 GUARDS: Validierung der erforderlichen Komponenten
    if not fetch_result.get('html'):
        raise ValueError("REGEL 1 VERLETZT: raw_html ist erforderlich aber fehlt")

    # Text-Extraktion
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

    if prev_page_map and canonical_url in prev_page_map:
        prev_page = prev_page_map[canonical_url]
        prev_sha256 = prev_page.get('sha256_text')

        if prev_sha256 and prev_sha256 == sha256_text:
            # UNVERÄNDERT: Hash-Gate aktiviert
            changed = False
            prev_page_id = prev_page['page_id']
            logger.debug(f"Hash-Gate: Page {canonical_url} unverändert (SHA256 gleich)")

    # Content-Type ermitteln
    content_type = fetch_result.get('headers', {}).get('content-type', 'text/html')

    # Page-Payload für Store
    page_payload = {
        'snapshot_id': snapshot_id,
        'url': fetch_result.get('original_url', fetch_result['final_url']),
        'final_url': fetch_result['final_url'],
        'status': fetch_result['status'],
        'fetched_at': fetch_result['fetched_at'],
        'via': fetch_result['via'],
        'content_type': content_type,
        'sha256_text': sha256_text,
        'title': title,
        'meta_description': meta_description,
        'canonical_url': canonical_url,
        'changed': changed,
        'prev_page_id': prev_page_id,
        'normalized_len': len(normalized_text),
        'extraction_version': EXTRACTION_VERSION
    }

    # FILE UPLOAD: Je nach Store-Typ
    if hasattr(store, 'upload_raw_and_text'):
        # Supabase Store: Upload to Storage first
        try:
            file_paths = await store.upload_raw_and_text(snapshot_id, str(uuid.uuid4()), fetch_result['html'], normalized_text)
            page_payload.update(file_paths)
        except Exception as e:
            logger.error(f"File upload failed for page, will save without files: {e}")
            # Continue without files - page will be saved but downloads won't work
    else:
        # SQLite Store: Local file paths
        import os
        import uuid as uuid_module

        page_id = str(uuid_module.uuid4())  # Generate temp ID for paths
        snapshot_dir = f"data/snapshots/{snapshot_id}/pages"
        os.makedirs(snapshot_dir, exist_ok=True)

        html_path = f"{snapshot_id}/pages/{page_id}.html"
        txt_path = f"{snapshot_id}/pages/{page_id}.txt"

        # Save files locally
        try:
            html_file_path = f"data/snapshots/{html_path}"
            with open(html_file_path, 'w', encoding='utf-8') as f:
                f.write(fetch_result['html'])

            txt_file_path = f"data/snapshots/{txt_path}"
            with open(txt_file_path, 'w', encoding='utf-8') as f:
                f.write(normalized_text)

            page_payload['raw_path'] = html_path
            page_payload['text_path'] = txt_path

        except Exception as e:
            logger.error(f"Local file save failed: {e}")
            raise

    # Save page via Store
    page_id = await store.insert_or_update_page(snapshot_id, page_payload)

    return {
        'id': page_id,
        'url': page_payload['url'],
        'status': page_payload['status'],
        'sha256_text': page_payload['sha256_text'],
        'title': page_payload['title'],
        'meta_description': page_payload['meta_description'],
        'canonical_url': canonical_url,
        'changed': changed,
        'prev_page_id': prev_page_id,
        'text_path': page_payload.get('text_path')
    }


async def create_profile_with_llm(competitor_id: str, snapshot_id: str, pages: List[Dict]) -> Optional[str]:
    """
    Erstellt ein Profil mit LLM basierend auf den gecrawlten Seiten

    Args:
        competitor_id: ID des Competitors
        snapshot_id: ID des Snapshots
        pages: Liste der gecrawlten Pages

    Returns:
        Profil-Text oder None bei Fehler
    """
    try:
        # OpenAI API Key aus Environment
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY nicht gesetzt, überspringe Profil-Erstellung")
            return "LLM-Profil nicht verfügbar (API-Key fehlt)"

        # Filtere relevante Seiten (keine privacy/terms, sortiere nach Textlänge)
        relevant_pages = []
        for page in pages:
            url_path = urlparse(page['url']).path.lower()
            if not any(exclude in url_path for exclude in ['privacy', 'terms']):
                relevant_pages.append(page)

        # Sortiere nach Textlänge (wir nehmen an, dass längerer Text mehr Inhalt hat)
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

            # Lade den normalisierten Text über Store (max 6000 chars pro Seite)
            if page.get('id'):
                try:
                    text_content = await store.download_page_text(page['id'])
                    if text_content:
                        text_str = text_content.decode('utf-8')[:6000]
                        if text_str.strip():
                            llm_input_parts.append(f"Inhalt: {text_str}")
                except Exception as e:
                    logger.warning(f"Fehler beim Laden der Textdatei für Page {page['id']}: {e}")

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
        import openai
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

        logger.info(f"LLM-Profil für Competitor {competitor_id} erstellt")
        return profile_text

    except Exception as e:
        logger.error(f"Fehler bei LLM-Profil-Erstellung: {e}")
        return None

async def get_snapshot(snapshot_id: str, with_previews: bool = False, preview_limit: int = 10) -> Optional[dict]:
    """Get complete snapshot data including pages."""
    try:
        return await store.get_snapshot(snapshot_id, with_previews, preview_limit)
    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshots: {e}")
        return None

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

                # Page speichern mit Hash-Gate
                page_info = await persist_page_snapshot(snapshot_id, fetch_dict, competitor_id, prev_page_map)
                if page_info:
                    saved_count += 1
                    # Progress erhöhen
                    await increment_snapshot_progress(snapshot_id)

            except Exception as e:
                logger.warning(f"[{scan_id}] Fehler beim Speichern von {fetch_result.url}: {e}")

        # Social Links extrahieren (global aus allen Seiten)
        try:
            await extract_social_links_from_snapshot(snapshot_id, competitor_id)
        except Exception as e:
            logger.error(f"[{scan_id}] Fehler bei Social Link Extraktion: {e}")

        # VALIDATION: Anzahl gespeicherter Pages == erwartete Gesamtanzahl
        await update_snapshot_page_count(snapshot_id)
        final_page_count = await get_snapshot_page_count(snapshot_id)
        expected_total = len(top_3_urls) + len(rest_urls)  # Gesamtanzahl aus Page-Set

        if final_page_count != expected_total:
            logger.error(f"[{scan_id}] VALIDATION FAILED: Erwartet {expected_total} Pages, aber {final_page_count} gespeichert")
            await update_snapshot_status(snapshot_id, "failed",
                                       error_code="VALIDATION_FAILED",
                                       error_message=f"Page count mismatch: expected {expected_total}, got {final_page_count}")
            return

        # LOGGING: Change Detection Stats
        change_counts = await get_snapshot_change_counts(snapshot_id)
        logger.info(f"[{scan_id}] SCAN COMPLETED - prev_snapshot: {prev_snapshot_id}, changed_pages: {change_counts['changed_pages_count']}, unchanged_pages: {change_counts['unchanged_pages_count']}, total: {change_counts['total_pages_count']}")

        # Snapshot als fertig markieren
        await update_snapshot_status(snapshot_id, "done", finished_at=datetime.now().isoformat())

        logger.info(f"[{scan_id}] PHASE B: Abgeschlossen - {saved_count} Seiten gespeichert, Status: done")

    except Exception as e:
        logger.error(f"[{scan_id}] PHASE B: Fataler Fehler: {e}")
        # Bei fatalem Fehler: Status auf failed setzen
        await update_snapshot_status(snapshot_id, "failed",
                                    error_code="BACKGROUND_ERROR",
                                    error_message=str(e))


async def extract_social_links_from_snapshot(snapshot_id: str, competitor_id: str):
    """
    Extrahiert Social Links aus allen Seiten eines Snapshots

    Args:
        snapshot_id: ID des Snapshots
        competitor_id: ID des Competitors
    """
    from services.persistence import extract_social_links

    try:
        # Alle Pages dieses Snapshots laden
        snapshot_data = await store.get_snapshot(snapshot_id)
        if not snapshot_data or not snapshot_data.get('pages'):
            return

        all_social_links = []
        for page in snapshot_data['pages']:
            try:
                # HTML über Store laden
                html_content = await store.download_page_raw(page['id'])
                if html_content:
                    html_str = html_content.decode('utf-8')
                # Social Links extrahieren
                    social_links = extract_social_links(html_str, page['url'])
                all_social_links.extend(social_links)

            except Exception as e:
                logger.warning(f"Fehler beim Laden der HTML für Social Links: {e}")

        # Social Links deduplizieren und speichern
        if all_social_links:
            await store.upsert_socials(competitor_id, all_social_links)
            logger.info(f"Social Links für Snapshot {snapshot_id} gespeichert: {len(all_social_links)}")

    except Exception as e:
        logger.error(f"Fehler bei Social Link Extraktion für Snapshot {snapshot_id}: {e}")

# API Endpoints
@app.post("/api/scan", response_model=ScanResponse)
@limiter.limit("10/minute")
async def scan_endpoint(scan_request: ScanRequest, request: Request):
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
        normalized_url = normalize_input_url(scan_request.url)
        validate_url_for_scanning(normalized_url)
        logger.info(f"[{scan_id}] URL normalisiert: {scan_request.url} -> {normalized_url}")
    except ValueError as e:
        logger.warning(f"[{scan_id}] Ungültige URL: {scan_request.url} - {str(e)}")
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
            competitor_id = await store.upsert_competitor(scan_request.name, normalized_url)
            logger.info(f"[{scan_id}] Competitor ID: {competitor_id}")

            # 2. URLs entdecken
            logger.info(f"[{scan_id}] Starte URL-Discovery...")
            discovered_urls = await discover_urls(normalized_url)
            discover_count = len(discovered_urls)
            logger.info(f"[{scan_id}] Discovery abgeschlossen: {discover_count} URLs gefunden")

            if not discovered_urls:
                return ScanResponse(
                    ok=False,
                    error=ErrorDetail(code="NO_URLS", message="Keine URLs zum Crawlen gefunden"),
                    competitor_id=competitor_id,
                    render_mode="httpx"  # fallback
                )

            # 3. DETERMINISTISCHES PAGE-SET ERSTELLEN (REGEL 2)
            page_set = create_deterministic_page_set(discovered_urls, normalized_url)
            final_urls = page_set["urls"]

            logger.info(f"[{scan_id}] Page-Set erstellt: {len(final_urls)} URLs (max {page_set['rules']['max_pages']})")

            # 4. PAGE-SET ÄNDERUNG PRÜFEN (RE-SCAN)
            page_set_changed = await check_page_set_changed(competitor_id, page_set["page_set_hash"])
            if page_set_changed:
                logger.info(f"[{scan_id}] Page-Set geändert seit letztem Scan")

            # 5. PREVIOUS SNAPSHOT LOOKUP für Change Detection
            prev_snapshot_id = await store.get_latest_snapshot_id(competitor_id)
            prev_page_map = {}

            if prev_snapshot_id:
                logger.info(f"[{scan_id}] Previous Snapshot gefunden: {prev_snapshot_id}")
                prev_page_map = await store.get_pages_map(prev_snapshot_id)
                logger.info(f"[{scan_id}] Previous Page-Map geladen: {len(prev_page_map)} Pages")
            else:
                logger.info(f"[{scan_id}] Kein Previous Snapshot gefunden (erster Scan)")

            # 6. URLs priorisieren (Top 3 vs Rest) - AUSSCHLIESSLICH aus Page-Set
            top_3_urls, rest_urls = prioritize_urls(final_urls, normalized_url)
            logger.info(f"[{scan_id}] URLs priorisiert: {len(top_3_urls)} Top-URLs, {len(rest_urls)} Rest-URLs")

            # 7. Render-Mode entscheiden und alle Fetches durchführen
            async with FetchManager() as fetch_manager:
                logger.info(f"[{scan_id}] Entscheide Render-Mode...")
                render_mode = await fetch_manager.decide_render_mode(normalized_url)
                logger.info(f"[{scan_id}] Render-Mode entschieden: {render_mode}")

                # 8. Snapshot erstellen mit Page-Set Metadaten
                snapshot_id = await store.create_snapshot(
                    competitor_id=competitor_id,
                    page_set_json=page_set,
                    page_set_hash=page_set["page_set_hash"],
                    progress_total=len(final_urls),
                    extraction_version=EXTRACTION_VERSION,
                    page_set_version=PAGE_SET_VERSION
                )

                # LOGGING: Scan-Start Informationen
                logger.info(f"[{scan_id}] SCAN START - extraction_version: {EXTRACTION_VERSION}, page_set_version: {PAGE_SET_VERSION}, page_set_hash: {page_set['page_set_hash'][:16]}..., page_count: {len(final_urls)}")
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

                        # Page speichern mit Hash-Gate
                        page_info = await persist_page_snapshot(snapshot_id, fetch_dict, competitor_id, prev_page_map)

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

                # 8. Optional: LLM-Profil erstellen (Priorität auf changed pages)
                if scan_request.llm and pages_data:
                    try:
                        logger.info(f"[{scan_id}] Erstelle LLM-Profil...")

                        # LLM RESTRICTION: Priorität auf changed pages
                        # Sammle changed vs unchanged pages
                        changed_pages_data = []
                        unchanged_pages_data = []

                        for page_data in pages_data:
                            # Finde entsprechende page_info
                            matching_page = next((p for p in pages_info if p.id == page_data.get('page_id')), None)
                            if matching_page and not matching_page.changed:
                                unchanged_pages_data.append(page_data)
                            else:
                                changed_pages_data.append(page_data)

                        # Priorität: changed pages zuerst, dann unchanged falls nötig
                        selected_pages_data = changed_pages_data[:3]  # Max 3 changed pages

                        if len(selected_pages_data) < 3 and unchanged_pages_data:
                            # Fülle mit unchanged pages auf (max 3 total)
                            needed = 3 - len(selected_pages_data)
                            selected_pages_data.extend(unchanged_pages_data[:needed])

                        logger.info(f"[{scan_id}] LLM verwendet {len(changed_pages_data)} changed + {len(unchanged_pages_data)} unchanged pages, selected {len(selected_pages_data)}")

                        profile = await create_profile_with_llm(competitor_id, snapshot_id, selected_pages_data)
                        if profile:
                            await store.save_profile(competitor_id, snapshot_id, profile)
                        logger.info(f"[{scan_id}] LLM-Profil erfolgreich erstellt")
                    except Exception as e:
                        logger.error(f"[{scan_id}] Fehler bei LLM-Profil-Erstellung: {e}")
                        profile = None  # Bei Fehler kein Profil setzen

                # 9. Status auf "partial" setzen
                await update_snapshot_status(snapshot_id, "partial")
                logger.info(f"[{scan_id}] Phase A abgeschlossen, Status: partial")

                # 10. PHASE B starten (asynchron, kein await!)
                if rest_urls:
                    task = asyncio.create_task(
                        complete_scan_background(
                            scan_id=scan_id,
                            snapshot_id=snapshot_id,
                            rest_urls=rest_urls,
                            render_mode=render_mode,
                            competitor_id=competitor_id
                        ),
                        name=f"scan-{scan_id}-phase-b"
                    )

                    # Task tracking für cleanup
                    _background_tasks.add(task)
                    task.add_done_callback(lambda t: _background_tasks.discard(t))

                    # Exception logging
                    def _log_task_exception(t):
                        try:
                            exc = t.exception()
                            if exc:
                                logger.error(f"[{scan_id}] Background task failed: {exc}", exc_info=exc)
                        except asyncio.CancelledError:
                            pass

                    task.add_done_callback(_log_task_exception)
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
                    progress=Progress(done=len(pages_info), total=len(final_urls))
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
async def get_competitors_endpoint():
    try:
        return await get_competitors()
    except Exception as e:
        logger.error(f"Fehler beim Laden der Competitors: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/api/competitors/{competitor_id}")
async def get_competitor_endpoint(competitor_id: str):
    try:
        competitor = await get_competitor(competitor_id)
        if not competitor:
            raise HTTPException(status_code=404, detail="Competitor nicht gefunden")
        return competitor
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden des Competitors: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/api/snapshots/{snapshot_id}/status")
async def get_snapshot_status_endpoint(snapshot_id: str):
    """Gibt den aktuellen Status eines Snapshots zurück"""
    try:
        # Snapshot über Store laden
        snapshot_data = await store.get_snapshot(snapshot_id)

        if not snapshot_data:
            raise HTTPException(status_code=404, detail="Snapshot nicht gefunden")

        # Status-Response erstellen
        status_data = {
            'snapshot_id': snapshot_data['id'],
            'status': snapshot_data['status'],
            'progress': {
                'done': snapshot_data['progress_pages_done'],
                'total': snapshot_data['progress_pages_total']
            }
        }

        # Error hinzufügen falls vorhanden
        if snapshot_data.get('error_code'):
            status_data['error'] = {
                'code': snapshot_data['error_code'],
                'message': snapshot_data['error_message'] or ''
            }

        # Change-Counts hinzufügen (berechne aus Pages)
        pages = snapshot_data.get('pages', [])
        changed_count = sum(1 for p in pages if p.get('changed', True))
        unchanged_count = len(pages) - changed_count

        status_data.update({
            'changed_pages_count': changed_count,
            'unchanged_pages_count': unchanged_count,
            'total_pages_count': len(pages)
        })

        return status_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshot-Status: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@app.get("/api/snapshots/{snapshot_id}")
async def get_snapshot_endpoint(snapshot_id: str, with_previews: bool = False, preview_limit: int = 10):
    """
    Holt einen Snapshot mit allen Seiten.

    Query-Parameter:
    - with_previews: Wenn true, werden Text-Previews für die ersten preview_limit Seiten geladen
    - preview_limit: Maximale Anzahl von Seiten mit Previews (default: 10)
    """
    try:
        snapshot = await store.get_snapshot(snapshot_id, with_previews=with_previews, preview_limit=preview_limit)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot nicht gefunden")
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden des Snapshots: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/api/pages/{page_id}/raw")
async def download_page_raw(page_id: str):
    """HTML-Datei als Download bereitstellen"""
    try:
        # HTML über Store laden
        html_content = await store.download_page_raw(page_id)

        if html_content is None:
            raise HTTPException(status_code=404, detail="HTML-Datei nicht gefunden")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden der HTML-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"HTML-Datei konnte nicht geladen werden: {str(e)}"
        )

@app.get("/api/pages/{page_id}/text")
async def download_page_text(page_id: str):
    """TXT-Datei als Download bereitstellen"""
    try:
        # Text über Store laden
        text_content = await store.download_page_text(page_id)

        if text_content is None:
            raise HTTPException(status_code=404, detail="TXT-Datei nicht gefunden")

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden der TXT-Datei für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"TXT-Datei konnte nicht geladen werden: {str(e)}"
        )

@app.get("/api/pages/{page_id}/preview")
async def get_page_preview(page_id: str):
    """Gibt eine Text-Preview für eine einzelne Seite zurück (300 Zeichen)"""
    try:
        # Text-Preview über Store laden
        preview = await store.get_page_preview(page_id, max_length=300)

        if preview is None:
            raise HTTPException(status_code=404, detail="Text-Datei nicht gefunden")

        return preview

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Laden der Text-Preview für Page {page_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Text-Preview konnte nicht geladen werden: {str(e)}"
        )

# SQLite DB nur initialisieren wenn SQLite verwendet wird (wird jetzt vom Store gemacht)
# @app.on_event("startup")
# def startup_event():
#     if PERSISTENCE_BACKEND == "sqlite":
#         from services.persistence import init_db
#         init_db()

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }


@app.get("/health/ready")
async def readiness_check():
    """Readiness check - verifies all dependencies are ready"""
    checks = {
        "database": False,
    }

    # Database Check
    try:
        # Versuche eine einfache DB-Operation
        await store.list_competitors()
        checks["database"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "timestamp": datetime.now().isoformat()
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
