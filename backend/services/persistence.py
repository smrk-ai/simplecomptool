import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
import openai
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Supabase Konfiguration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SERVICE_ROLE_KEY = os.getenv("SERVICE_ROLE_KEY")

# Supabase Client
supabase: Optional[Client] = None

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
    """Initialisiert die Supabase-Verbindung"""
    global supabase

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("SUPABASE_URL und SUPABASE_ANON_KEY müssen gesetzt sein")

    # Supabase Client mit Anon Key für normale Operationen
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    logger.info("Supabase-Verbindung initialisiert")

    # Erstelle Buckets mit Service Role Key falls verfügbar
    if SERVICE_ROLE_KEY:
        admin_client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

        # Stelle sicher, dass die Buckets existieren
        try:
            # HTML-Dateien Bucket
            admin_client.storage.create_bucket("html-files")
            logger.info("Bucket 'html-files' erstellt")
        except Exception as e:
            error_str = str(e).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                logger.info("Bucket 'html-files' existiert bereits")
            else:
                logger.warning(f"Fehler beim Erstellen des HTML-Buckets: {e}")

        try:
            # TXT-Dateien Bucket
            admin_client.storage.create_bucket("txt-files")
            logger.info("Bucket 'txt-files' erstellt")
        except Exception as e:
            error_str = str(e).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                logger.info("Bucket 'txt-files' existiert bereits")
            else:
                logger.warning(f"Fehler beim Erstellen des TXT-Buckets: {e}")

        logger.info("Supabase Storage Buckets bereit")
    else:
        logger.warning("SERVICE_ROLE_KEY nicht verfügbar - Buckets müssen manuell erstellt werden")


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


def get_or_create_competitor(base_url: str, name: Optional[str] = None) -> str:
    """Holt oder erstellt einen Competitor anhand der base_url"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    # Normalisiere base_url
    parsed = urlparse(base_url)
    normalized_base_url = f"{parsed.scheme}://{parsed.netloc}"

    try:
        # Suche existierenden Competitor
        result = supabase.table('competitors').select('id').eq('base_url', normalized_base_url).execute()

        if result.data:
            competitor_id = result.data[0]['id']
            logger.info(f"Existierender Competitor gefunden: {competitor_id}")
        else:
            # Erstelle neuen Competitor
            competitor_id = str(uuid.uuid4())
            data = {
                'id': competitor_id,
                'name': name,
                'base_url': normalized_base_url,
                'created_at': datetime.now().isoformat()
            }
            supabase.table('competitors').insert(data).execute()
            logger.info(f"Neuer Competitor erstellt: {competitor_id}")

        return competitor_id

    except Exception as e:
        logger.error(f"Fehler bei Competitor-Operation: {e}")
        raise


def create_snapshot(competitor_id: str, page_count: int = 0, notes: Optional[str] = None) -> str:
    """Erstellt einen neuen Snapshot"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    snapshot_id = str(uuid.uuid4())
    data = {
        'id': snapshot_id,
        'competitor_id': competitor_id,
        'created_at': datetime.now().isoformat(),
        'page_count': page_count,
        'notes': notes
    }

    try:
        supabase.table('snapshots').insert(data).execute()
        logger.info(f"Snapshot erstellt: {snapshot_id}")
        return snapshot_id
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Snapshots: {e}")
        raise


def save_page(snapshot_id: str, fetch_result: Dict, competitor_id: str) -> Dict:
    """
    Speichert eine Page mit allen Dateien und Metadaten in Supabase

    Args:
        snapshot_id: ID des Snapshots
        fetch_result: Ergebnis von fetch_url()
        competitor_id: ID des Competitors

    Returns:
        Dict mit Page-Daten für API Response
    """
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    page_id = str(uuid.uuid4())

    # Text-Extraktion
    title, meta_description, normalized_text = extract_text_from_html(fetch_result['html'])
    sha256_text = calculate_text_hash(normalized_text)

    # Supabase Storage Pfade
    html_path = f"{snapshot_id}/pages/{page_id}.html"
    txt_path = f"{snapshot_id}/pages/{page_id}.txt"

    try:
        # HTML-Datei zu Supabase Storage hochladen
        html_bytes = fetch_result['html'].encode('utf-8')
        supabase.storage.from_('html-files').upload(
            path=html_path,
            file=html_bytes,
            file_options={"content-type": "text/html"}
        )

        # TXT-Datei zu Supabase Storage hochladen
        txt_bytes = normalized_text.encode('utf-8')
        supabase.storage.from_('txt-files').upload(
            path=txt_path,
            file=txt_bytes,
            file_options={"content-type": "text/plain"}
        )

    except Exception as e:
        logger.error(f"Fehler beim Hochladen der Dateien für Page {page_id}: {e}")
        return None

    # Content-Type ermitteln
    content_type = fetch_result.get('headers', {}).get('content-type', 'text/html')

    # In Supabase Datenbank speichern
    data = {
        'id': page_id,
        'snapshot_id': snapshot_id,
        'url': fetch_result.get('original_url', fetch_result['final_url']),
        'final_url': fetch_result['final_url'],
        'status': fetch_result['status'],
        'fetched_at': fetch_result['fetched_at'],
        'via': fetch_result['via'],
        'content_type': content_type,
        'raw_path': html_path,
        'text_path': txt_path,
        'sha256_text': sha256_text,
        'title': title,
        'meta_description': meta_description
    }

    try:
        supabase.table('pages').insert(data).execute()

        # Social Links extrahieren und speichern
        social_links = extract_social_links(fetch_result['html'], fetch_result['final_url'])
        save_social_links(competitor_id, social_links, fetch_result['final_url'])

        logger.info(f"Page gespeichert: {page_id}")

        return {
            'id': page_id,
            'url': fetch_result.get('original_url', fetch_result['final_url']),
            'status': fetch_result['status'],
            'sha256_text': sha256_text,
            'title': title,
            'meta_description': meta_description,
            'text_path': txt_path
        }

    except Exception as e:
        logger.error(f"Fehler beim Speichern der Page {page_id}: {e}")
        return None


def save_social_links(competitor_id: str, social_links: List[Dict], source_url: str):
    """Speichert Social Media Links (unique per competitor/platform/handle)"""
    if not social_links or not supabase:
        return

    try:
        for social in social_links:
            try:
                # Supabase upsert (on_conflict)
                data = {
                    'id': str(uuid.uuid4()),
                    'competitor_id': competitor_id,
                    'platform': social['platform'],
                    'handle': social['handle'],
                    'url': social['url'],
                    'discovered_at': datetime.now().isoformat(),
                    'source_url': source_url
                }

                supabase.table('socials').upsert(
                    data,
                    on_conflict='competitor_id,platform,handle'
                ).execute()

            except Exception as e:
                logger.warning(f"Fehler beim Speichern von Social Link {social}: {e}")
                continue

        logger.info(f"{len(social_links)} Social Links für Competitor {competitor_id} gespeichert")

    except Exception as e:
        logger.error(f"Fehler beim Speichern der Social Links: {e}")


def update_snapshot_page_count(snapshot_id: str):
    """Aktualisiert die page_count eines Snapshots"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    try:
        # Zähle Pages für diesen Snapshot
        result = supabase.table('pages').select('id', count='exact').eq('snapshot_id', snapshot_id).execute()
        count = result.count

        # Aktualisiere Snapshot
        supabase.table('snapshots').update({'page_count': count}).eq('id', snapshot_id).execute()

        logger.info(f"Snapshot {snapshot_id} page_count auf {count} aktualisiert")

    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren der page_count: {e}")


def get_competitor_socials(competitor_id: str) -> List[Dict]:
    """Holt alle Social Media Accounts eines Competitors"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    try:
        result = supabase.table('socials').select(
            'platform, handle, url, discovered_at, source_url'
        ).eq('competitor_id', competitor_id).execute()

        return result.data
    except Exception as e:
        logger.error(f"Fehler beim Laden der Social Links: {e}")
        return []


def get_snapshot_pages(snapshot_id: str) -> List[Dict]:
    """Holt alle Pages eines Snapshots"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    try:
        result = supabase.table('pages').select(
            'id, url, final_url, status, fetched_at, via, content_type, '
            'raw_path, text_path, sha256_text, title, meta_description'
        ).eq('snapshot_id', snapshot_id).order('fetched_at').execute()

        return result.data
    except Exception as e:
        logger.error(f"Fehler beim Laden der Pages: {e}")
        return []


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
            return None

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

            # Lade den normalisierten Text aus Supabase Storage (max 6000 chars pro Seite)
            if page.get('text_path'):
                try:
                    # Datei von Supabase Storage herunterladen
                    response = supabase.storage.from_('txt-files').download(page['text_path'])
                    text_content = response.decode('utf-8')[:6000]  # Max 6000 chars pro Seite
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

        # Speichere Profil in Datenbank
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        data = {
            'id': str(uuid.uuid4()),
            'competitor_id': competitor_id,
            'snapshot_id': snapshot_id,
            'created_at': datetime.now().isoformat(),
            'text': profile_text
        }

        supabase.table('profiles').insert(data).execute()

        logger.info(f"Profil für Competitor {competitor_id} erstellt und gespeichert")
        return profile_text

    except Exception as e:
        logger.error(f"Fehler bei LLM-Profil-Erstellung: {e}")
        return None


def get_competitor_profile(competitor_id: str, snapshot_id: Optional[str] = None) -> Optional[Dict]:
    """Holt das neueste Profil eines Competitors (oder für einen spezifischen Snapshot)"""
    if not supabase:
        raise RuntimeError("Supabase nicht initialisiert")

    try:
        query = supabase.table('profiles').select(
            'id, snapshot_id, created_at, text'
        ).eq('competitor_id', competitor_id)

        if snapshot_id:
            query = query.eq('snapshot_id', snapshot_id)

        result = query.order('created_at', desc=True).limit(1).execute()

        if result.data:
            return result.data[0]

        return None

    except Exception as e:
        logger.error(f"Fehler beim Laden des Profils: {e}")
        return None
