# 🐛 BUGFIX TODO - Simple CompTool v3

**Letzte Aktualisierung:** 2025-12-27
**Status:** 18 Bugs identifiziert | 0 behoben | 18 offen

---

## 🚨 CRITICAL - SOFORT BEHEBEN! (Vor Deployment)

### ⚠️ BUG #5: SQL Schema vs. Code Mismatch
**Priorität:** P0 (BLOCKER)
**Impact:** Alle Page-Saves schlagen fehl, App ist nicht funktionsfähig
**Geschätzte Zeit:** 30 Minuten
**Dateien:** `supabase_schema.sql`, `backend/services/persistence.py:407-414`

**Problem:**
- SQL Schema fehlt 8 Spalten die im Code verwendet werden
- DB Insert schlägt fehl mit "column does not exist"

**Lösung:**
```sql
-- In Supabase SQL Editor ausführen:
ALTER TABLE pages ADD COLUMN IF NOT EXISTS canonical_url TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS changed BOOLEAN DEFAULT TRUE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS prev_page_id UUID;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS text_length INTEGER;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS normalized_len INTEGER;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS has_truncation BOOLEAN DEFAULT FALSE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS extraction_version TEXT DEFAULT 'v1';
ALTER TABLE pages ADD COLUMN IF NOT EXISTS fetch_duration FLOAT;

-- Index für Performance
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(snapshot_id, canonical_url);
```

**Testen:**
```bash
# Nach Fix einen Test-Scan durchführen
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #6: Duplicate Policy Names in SQL Schema
**Priorität:** P0 (BLOCKER)
**Impact:** Datenbank-Initialisierung schlägt fehl
**Geschätzte Zeit:** 15 Minuten
**Dateien:** `supabase_schema.sql:73-78`

**Problem:**
- 5 Policies mit identischem Namen "Allow all operations for anon"
- Supabase erfordert unique Policy-Namen
- SQL Script schlägt ab zweiter Policy fehl

**Lösung:**
```sql
-- Alte Policies löschen (falls vorhanden)
DROP POLICY IF EXISTS "Allow all operations for anon" ON competitors;
DROP POLICY IF EXISTS "Allow all operations for anon" ON snapshots;
DROP POLICY IF EXISTS "Allow all operations for anon" ON pages;
DROP POLICY IF EXISTS "Allow all operations for anon" ON socials;
DROP POLICY IF EXISTS "Allow all operations for anon" ON profiles;

-- Neue Policies mit eindeutigen Namen
CREATE POLICY "Allow all for anon on competitors" ON competitors FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on snapshots" ON snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on pages" ON pages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on socials" ON socials FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on profiles" ON profiles FOR ALL USING (true) WITH CHECK (true);
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #14: Storage Bucket Name Mismatch
**Priorität:** P0 (BLOCKER)
**Impact:** Alle File-Uploads schlagen fehl
**Geschätzte Zeit:** 20 Minuten
**Dateien:** `backend/services/persistence.py:81-99, 335-346`

**Problem:**
- `init_db()` erstellt Buckets: `html-files`, `txt-files`
- `save_page()` uploaded in Bucket: `snapshots`
- Bucket existiert nicht → Upload schlägt fehl

**Lösung Option A (Empfohlen):**
```python
# backend/services/persistence.py

def init_db():
    # ...
    try:
        # Einen gemeinsamen Bucket für alles
        admin_client.storage.create_bucket("snapshots")
        logger.info("Bucket 'snapshots' erstellt")
    except Exception as e:
        error_str = str(e).lower()
        if "already exists" in error_str or "duplicate" in error_str:
            logger.info("Bucket 'snapshots' existiert bereits")
        else:
            logger.warning(f"Fehler beim Erstellen des Snapshots-Buckets: {e}")

def save_page(...):
    # Bleibt gleich - nutzt 'snapshots' Bucket
    supabase.storage.from_('snapshots').upload(html_path, ...)
    supabase.storage.from_('snapshots').upload(txt_path, ...)
```

**Testen:**
```python
# In Supabase Dashboard prüfen:
# Storage > Buckets > "snapshots" sollte existieren
```

**Status:** ⬜ TODO

---

### 🔒 SECURITY #15: SSRF Vulnerability - Keine URL Validation
**Priorität:** P0 (SECURITY CRITICAL)
**Impact:** Server kann interne Services angreifen, Metadata auslesen
**Geschätzte Zeit:** 1 Stunde
**Dateien:** `backend/main.py:259-506`, `frontend/app/page.tsx:59-70`

**Problem:**
- User kann URLs wie `http://localhost:8000/admin` eingeben → SSRF
- User kann URLs wie `http://169.254.169.254/latest/meta-data/` eingeben → AWS Metadata Leak
- Keine Validierung von URL-Schema, Domain, IP-Range

**Lösung:**
```python
# backend/validators.py (NEU erstellen)
from fastapi import HTTPException
import re
from urllib.parse import urlparse

PRIVATE_IP_REGEX = r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.)'
AWS_METADATA_IP = '169.254.169.254'

def validate_scan_url(url: str) -> str:
    """
    Validiert URL für Scan-Requests.

    Blockiert:
    - Ungültige Schemas (nicht http/https)
    - Private IP-Ranges (10.x, 172.16-31.x, 192.168.x, 127.x)
    - Localhost
    - AWS Metadata-Service
    - Zu lange URLs (>2048 chars)
    """
    # Length check
    if not url or len(url) > 2048:
        raise HTTPException(400, detail={
            "error": {
                "code": "INVALID_URL_LENGTH",
                "message": "URL muss zwischen 1-2048 Zeichen sein"
            }
        })

    url = url.strip()

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(400, detail={
            "error": {
                "code": "INVALID_URL_FORMAT",
                "message": "URL-Format ist ungültig"
            }
        })

    # Schema validation
    if parsed.scheme and parsed.scheme not in ['http', 'https']:
        raise HTTPException(400, detail={
            "error": {
                "code": "INVALID_URL_SCHEME",
                "message": f"Ungültiges URL-Schema: {parsed.scheme}. Nur http und https erlaubt."
            }
        })

    # SSRF Protection: Block private IPs
    if parsed.hostname:
        hostname = parsed.hostname.lower()

        # Localhost variants
        if hostname in ['localhost', '0.0.0.0', '::1', '127.0.0.1']:
            raise HTTPException(400, detail={
                "error": {
                    "code": "LOCALHOST_NOT_ALLOWED",
                    "message": "Localhost-URLs sind nicht erlaubt"
                }
            })

        # AWS Metadata Service
        if hostname == AWS_METADATA_IP:
            raise HTTPException(400, detail={
                "error": {
                    "code": "METADATA_SERVICE_BLOCKED",
                    "message": "Zugriff auf Metadata-Service nicht erlaubt"
                }
            })

        # Private IP ranges
        if re.match(PRIVATE_IP_REGEX, hostname):
            raise HTTPException(400, detail={
                "error": {
                    "code": "PRIVATE_IP_NOT_ALLOWED",
                    "message": "Private IP-Adressen sind nicht erlaubt"
                }
            })

    return url

# backend/main.py
from validators import validate_scan_url

@app.post("/api/scan", response_model=ScanResponse)
async def scan_endpoint(request: ScanRequest):
    # ✅ VALIDATE FIRST!
    request.url = validate_scan_url(request.url)

    # ... rest der Logik
```

**Frontend Validation:**
```typescript
// frontend/app/page.tsx
const normalizeUrl = (input: string): string => {
    const trimmed = input.trim();
    if (!trimmed) throw new Error("URL darf nicht leer sein");

    // Blockiere gefährliche Schemas
    if (trimmed.match(/^(javascript|data|file|ftp):/i)) {
        throw new Error("Ungültiges URL-Schema");
    }

    // Validiere Domain-Format
    const domainRegex = /^[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,}$/;
    if (!trimmed.match(/^https?:\/\//i) && !domainRegex.test(trimmed.split('/')[0])) {
        throw new Error("Ungültiges Domain-Format");
    }

    return trimmed.match(/^https?:\/\//i) ? trimmed : `https://${trimmed}`;
};
```

**Testen:**
```bash
# Sollte blockiert werden:
curl -X POST http://localhost:8000/api/scan \
  -d '{"url":"http://localhost:8000/admin"}' # BLOCKED
curl -X POST http://localhost:8000/api/scan \
  -d '{"url":"http://169.254.169.254/latest/meta-data/"}' # BLOCKED
curl -X POST http://localhost:8000/api/scan \
  -d '{"url":"javascript:alert(1)"}' # BLOCKED

# Sollte erlaubt sein:
curl -X POST http://localhost:8000/api/scan \
  -d '{"url":"https://example.com"}' # ALLOWED
```

**Status:** ⬜ TODO

---

## 🔴 HIGH - Diese Woche beheben

### ⚠️ BUG #1: Race Condition in get_previous_snapshot_map()
**Priorität:** P1 (HIGH)
**Impact:** Inkorrekte Change Detection bei parallelen Scans
**Geschätzte Zeit:** 1 Stunde
**Dateien:** `backend/services/persistence.py:678-733`, `backend/main.py:312-316`

**Problem:**
- Zwei parallele Scans für denselben Competitor
- Beide laden denselben "previous" Snapshot (weil ORDER BY created_at DESC LIMIT 1)
- Scan 1 erstellt neuen Snapshot
- Scan 2 kennt den neuen Snapshot noch nicht
- Result: Falsche Change-Stats

**Lösung:**
```python
# backend/services/persistence.py
async def get_previous_snapshot_map(
    competitor_id: str,
    exclude_snapshot_id: Optional[str] = None  # ✅ Neuer Parameter
) -> dict:
    """Lädt neuesten Snapshot BEFORE exclude_snapshot_id"""

    query = supabase.table("snapshots")\
        .select("id, created_at")\
        .eq("competitor_id", competitor_id)\
        .order("created_at", desc=True)

    # Exclude current snapshot if provided
    if exclude_snapshot_id:
        query = query.neq("id", exclude_snapshot_id)

    result = query.limit(1).execute()

    if not result.data:
        return {}

    prev_snapshot_id = result.data[0]['id']
    # ... rest bleibt gleich

# backend/main.py
# Option A: Load previous NACH snapshot creation
snapshot_id = create_snapshot(competitor_id)  # ✅ Erst erstellen
prev_map = await get_previous_snapshot_map(
    competitor_id,
    exclude_snapshot_id=snapshot_id  # ✅ Dann laden mit Exclude
)

# Option B: Nutze DB Lock
# (komplexer, aber sicherer bei sehr hohem Traffic)
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #2: Storage Path Inconsistenz (Lokaler Fallback)
**Priorität:** P1 (HIGH)
**Impact:** Downloads schlagen fehl wenn Supabase Storage nicht erreichbar
**Geschätzte Zeit:** 30 Minuten
**Dateien:** `backend/main.py:605-685`

**Problem:**
```python
# save_page() speichert: "{snapshot_id}/pages/{page_id}.html"
# download_raw() sucht: "backend/data/snapshots/{snapshot_id}/pages/{page_id}.html"
# → Pfade stimmen nicht überein!
```

**Lösung Option A (Empfohlen): Entferne lokalen Fallback**
```python
# backend/main.py
@app.get("/api/pages/{page_id}/raw")
async def download_raw(page_id: str):
    try:
        supabase = _ensure_supabase()

        page_result = supabase.table("pages")\
            .select("raw_path")\
            .eq("id", page_id)\
            .single()\
            .execute()

        if not page_result.data or not page_result.data.get('raw_path'):
            raise HTTPException(404, "Page not found")

        raw_path = page_result.data['raw_path']

        # Nur Supabase Storage (kein lokaler Fallback)
        file_data = supabase.storage.from_("snapshots").download(raw_path)
        return Response(content=file_data, media_type="text/html; charset=utf-8")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(500, detail="Download fehlgeschlagen")
```

**Status:** ⬜ TODO

---

### 🔒 SECURITY #16: CORS Configuration - Production Fallback fehlt
**Priorität:** P1 (HIGH)
**Impact:** Frontend kann in Production nicht auf API zugreifen
**Geschätzte Zeit:** 30 Minuten
**Dateien:** `backend/main.py:28-59`

**Problem:**
- Wenn `CORS_ORIGINS` nicht gesetzt → Fallback auf `localhost:3000`
- In Production kann Frontend nicht auf API zugreifen
- Admin setzt dann frustriert `CORS_ORIGINS=*` → Security Hole

**Lösung:**
```python
# backend/main.py
def _get_cors_origins() -> List[str]:
    origins_str = os.getenv("CORS_ORIGINS")

    # Check if running in production
    is_production = bool(
        os.getenv("RAILWAY_ENVIRONMENT") or
        os.getenv("VERCEL") or
        os.getenv("PRODUCTION")
    )

    # Production: CORS_ORIGINS ist REQUIRED
    if not origins_str:
        if is_production:
            raise ValueError(
                "❌ CORS_ORIGINS Environment-Variable muss in Production gesetzt sein!\n"
                "Beispiel: CORS_ORIGINS=https://myapp.vercel.app,https://www.myapp.com"
            )
        else:
            # Development Fallback
            logger.info("🔧 Development Mode: Using localhost CORS")
            return ["http://localhost:3000"]

    # Parse und validiere Origins
    origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]

    # Security: Wildcard blockieren
    if "*" in origins:
        logger.error("🚨 CORS Wildcard (*) detected - SECURITY RISK!")
        if is_production:
            raise ValueError("Wildcard CORS ist in Production nicht erlaubt!")
        logger.warning("⚠️  Falling back to localhost only")
        return ["http://localhost:3000"]

    # Validierung: Alle Origins müssen gültige URLs sein
    valid_origins = []
    for origin in origins:
        if origin.startswith("http://") or origin.startswith("https://"):
            valid_origins.append(origin)
        else:
            logger.warning(f"⚠️  Invalid CORS origin (must start with http:// or https://): {origin}")

    if not valid_origins:
        raise ValueError("Keine gültigen CORS Origins gefunden!")

    logger.info(f"✅ CORS Origins configured: {', '.join(valid_origins)}")
    return valid_origins
```

**Deployment Checklist:**
```bash
# Railway Backend
railway variables set CORS_ORIGINS="https://yourapp.vercel.app"

# Oder für multiple Domains
railway variables set CORS_ORIGINS="https://yourapp.vercel.app,https://www.yourapp.com"
```

**Status:** ⬜ TODO

---

### 🔒 SECURITY #17: Missing Rate Limiting
**Priorität:** P1 (HIGH)
**Impact:** DoS-Attacken möglich, Server-Absturz durch RAM-Erschöpfung
**Geschätzte Zeit:** 1 Stunde
**Dateien:** `backend/main.py:259`, `backend/requirements.txt`

**Problem:**
- Keine Rate Limits auf `/api/scan`
- Attacker kann 1000 Requests/Sekunde senden
- Jeder Request startet Playwright-Instanz
- Server-RAM erschöpft → Crash

**Lösung:**
```bash
# backend/requirements.txt
slowapi==0.1.9
```

```python
# backend/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Limiter initialisieren
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Rate Limits anwenden
@app.post("/api/scan", response_model=ScanResponse)
@limiter.limit("5/minute")  # ✅ Max 5 Scans pro Minute pro IP
async def scan_endpoint(request: Request, scan_request: ScanRequest):
    # ... rest bleibt gleich

@app.get("/api/competitors")
@limiter.limit("60/minute")  # Lesezugriff großzügiger
async def get_competitors_endpoint(request: Request):
    # ...

@app.get("/api/snapshots/{snapshot_id}")
@limiter.limit("30/minute")
async def get_snapshot_details(request: Request, snapshot_id: str):
    # ...
```

**Konfigurierbar machen:**
```python
# config.py (NEU)
SCAN_RATE_LIMIT = os.getenv("SCAN_RATE_LIMIT", "5/minute")
READ_RATE_LIMIT = os.getenv("READ_RATE_LIMIT", "60/minute")

# main.py
@limiter.limit(SCAN_RATE_LIMIT)
async def scan_endpoint(...):
    # ...
```

**Testen:**
```bash
# Test Rate Limit
for i in {1..10}; do
  curl -X POST http://localhost:8000/api/scan \
    -H "Content-Type: application/json" \
    -d '{"url":"https://example.com"}'
  echo "Request $i"
done

# Nach 5 Requests sollte kommen:
# HTTP 429 Too Many Requests
# {"error":"Rate limit exceeded: 5 per 1 minute"}
```

**Status:** ⬜ TODO

---

## 🟡 MEDIUM - Nächste 2 Wochen

### ⚠️ BUG #3: Missing URL Validation im Frontend
**Priorität:** P2 (MEDIUM)
**Impact:** Kryptische Fehlermeldungen bei ungültigen URLs
**Geschätzte Zeit:** 30 Minuten
**Dateien:** `frontend/app/page.tsx:59-70`

**Problem:**
```typescript
// Aktuell: Kein Error Handling
return `https://${trimmed}`;  // Kann zu https://javascript:alert(1) führen
```

**Lösung:** Siehe SECURITY #15 (Frontend-Teil)

**Status:** ⬜ TODO

---

### ⚠️ BUG #4: Incorrect Error Handling in save_page()
**Priorität:** P2 (MEDIUM)
**Impact:** Pages gehen verloren bei Storage-Fehler, Stats sind falsch
**Geschätzte Zeit:** 45 Minuten
**Dateien:** `backend/services/persistence.py:349-386`

**Problem:**
- Bei Storage-Fehler wird `None` zurückgegeben
- Page wurde NIE in DB gespeichert → Daten verloren
- `fetch_success_count` wird nicht inkrementiert

**Lösung:**
```python
# backend/services/persistence.py
def save_page(snapshot_id: str, fetch_result: Dict, competitor_id: str) -> Dict:
    # ... text extraction ...

    # Storage Pfade
    html_path = f"{snapshot_id}/pages/{page_id}.html"
    txt_path = f"{snapshot_id}/pages/{page_id}.txt"

    storage_success = True
    storage_error = None

    try:
        # Storage Upload
        supabase.storage.from_('snapshots').upload(html_path, html_bytes, ...)
        supabase.storage.from_('snapshots').upload(txt_path, txt_bytes, ...)
    except Exception as e:
        storage_success = False
        storage_error = str(e)

        # Logging (wie vorher)
        error_str = str(e).lower()
        if "quota" in error_str:
            logger.critical(f"🚨 STORAGE QUOTA EXCEEDED!")
        # ... rest

    # ✅ IMMER in DB speichern (auch bei Storage-Fehler!)
    data = {
        'id': page_id,
        'snapshot_id': snapshot_id,
        # ... alle Felder ...

        # Storage-Status
        'raw_path': html_path if storage_success else None,
        'text_path': txt_path if storage_success else None,
        'storage_status': 'success' if storage_success else 'error',
        'storage_error': storage_error
    }

    try:
        supabase.table('pages').insert(data).execute()
        logger.info(f"Page gespeichert: {page_id} (storage: {storage_success})")

        # Social Links (wie vorher)
        social_links = extract_social_links(...)
        save_social_links(...)

        return {
            'id': page_id,
            'url': fetch_result.get('original_url', fetch_result['final_url']),
            'status': fetch_result['status'],
            'storage_success': storage_success,
            # ...
        }
    except Exception as db_error:
        logger.error(f"DB Insert failed for page {page_id}: {db_error}")
        return None  # Nur bei DB-Fehler None zurückgeben
```

**Schema Update:**
```sql
ALTER TABLE pages ADD COLUMN IF NOT EXISTS storage_status TEXT DEFAULT 'success';
ALTER TABLE pages ADD COLUMN IF NOT EXISTS storage_error TEXT;
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #7: Async/Sync Mix in create_profile_with_llm()
**Priorität:** P2 (MEDIUM)
**Impact:** Event Loop blockiert bei LLM-Profil-Erstellung
**Geschätzte Zeit:** 1 Stunde
**Dateien:** `backend/services/persistence.py:582`

**Problem:**
```python
# Sync Call in async Function!
response = supabase.storage.from_('txt-files').download(page['text_path'])
```

**Lösung:**
```python
# backend/services/persistence.py
import httpx

async def download_text_from_storage(text_path: str) -> str:
    """Async download from Supabase Storage"""
    storage_url = f"{SUPABASE_URL}/storage/v1/object/snapshots/{text_path}"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            storage_url,
            headers={"Authorization": f"Bearer {SERVICE_ROLE_KEY}"}
        )
        response.raise_for_status()
        return response.text

async def create_profile_with_llm(...):
    # ...
    for page in selected_pages:
        if page.get('text_path'):
            try:
                # ✅ Async download
                text_content = await download_text_from_storage(page['text_path'])
                text_content = text_content[:6000]
                if text_content.strip():
                    llm_input_parts.append(f"Inhalt: {text_content}")
            except Exception as e:
                logger.warning(f"Fehler beim Laden der Textdatei: {e}")
    # ...
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #9: Fehlende Error Handling bei API-Calls im Results Page
**Priorität:** P2 (MEDIUM)
**Impact:** Schlechte UX bei Netzwerkfehlern
**Geschätzte Zeit:** 30 Minuten
**Dateien:** `frontend/app/results/[snapshot_id]/page.tsx:55-70`

**Problem:**
- Kein Timeout → User wartet endlos
- Keine Retry-Logik
- Keine differenzierte Fehlerbehandlung

**Lösung:**
```typescript
// frontend/app/results/[snapshot_id]/page.tsx
const loadSnapshot = async () => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

    try {
        const response = await fetch(
            `${API_BASE_URL}/api/snapshots/${snapshot_id}`,
            { signal: controller.signal }
        );

        clearTimeout(timeoutId);

        // Differenzierte Fehlerbehandlung
        if (response.status === 404) {
            throw new Error('Snapshot wurde nicht gefunden. Wurde er gelöscht?');
        } else if (response.status === 403) {
            throw new Error('Keine Berechtigung für diesen Snapshot');
        } else if (response.status >= 500) {
            throw new Error('Server-Fehler. Bitte versuche es später erneut.');
        } else if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        setSnapshot(data);
    } catch (err) {
        if (err.name === 'AbortError') {
            setError('⏱️ Zeitüberschreitung beim Laden der Daten (30s)');
        } else if (err instanceof TypeError && err.message.includes('fetch')) {
            setError('🌐 Netzwerk-Fehler. Ist der Server erreichbar?');
        } else {
            setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
        }
    } finally {
        setLoading(false);
    }
};
```

**Status:** ⬜ TODO

---

### ⚠️ BUG #10: Environment Variable Fallback unsicher
**Priorität:** P2 (MEDIUM)
**Impact:** Production-Build schlägt fehl oder nutzt localhost
**Geschätzte Zeit:** 15 Minuten
**Dateien:** `frontend/app/page.tsx:12`, `frontend/app/results/[snapshot_id]/page.tsx:6`

**Problem:**
```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
// In Production fehlt NEXT_PUBLIC_API_URL → localhost → FAIL
```

**Lösung:**
```typescript
// frontend/config/api.ts (NEU)
export const API_BASE_URL = (() => {
    const url = process.env.NEXT_PUBLIC_API_URL;

    // Production: REQUIRED
    if (process.env.NODE_ENV === 'production' && !url) {
        throw new Error(
            'NEXT_PUBLIC_API_URL muss in Production gesetzt sein!\n' +
            'In Vercel: Settings > Environment Variables > NEXT_PUBLIC_API_URL'
        );
    }

    // Development: Fallback
    return url || 'http://localhost:8000';
})();

// frontend/app/page.tsx
import { API_BASE_URL } from '@/config/api';
// ... nutze API_BASE_URL
```

**Vercel Deployment:**
```bash
# In Vercel Dashboard:
# Settings > Environment Variables
NEXT_PUBLIC_API_URL=https://your-backend.railway.app
```

**Status:** ⬜ TODO

---

### 🐌 PERFORMANCE #11: N+1 Query Problem
**Priorität:** P2 (MEDIUM)
**Impact:** 3× DB-Queries statt 1, langsame API bei vielen Competitors
**Geschätzte Zeit:** 45 Minuten
**Dateien:** `backend/main.py:183-218`

**Problem:**
```python
# 3 separate Queries:
competitor = supabase.table('competitors').select(...)  # Query 1
competitor["socials"] = get_competitor_socials(...)     # Query 2
snapshots = supabase.table('snapshots').select(...)     # Query 3
```

**Lösung:**
```python
# backend/main.py
def get_competitor(competitor_id: str) -> Optional[dict]:
    try:
        supabase = _ensure_supabase()

        # ✅ Alles in 1 Query mit JOIN
        result = supabase.table('competitors').select('''
            id,
            name,
            base_url,
            created_at,
            snapshots(id, created_at, page_count, notes),
            socials(platform, handle, url, discovered_at)
        ''').eq('id', competitor_id).single().execute()

        if not result.data:
            return None

        competitor = result.data

        # Sortiere Snapshots nach Datum (neueste zuerst)
        if competitor.get('snapshots'):
            competitor['snapshots'] = sorted(
                competitor['snapshots'],
                key=lambda s: s['created_at'],
                reverse=True
            )

        return competitor

    except Exception as e:
        logger.error(f"Fehler beim Laden des Competitors: {e}")
        return None
```

**Testen:**
```python
# Vor Fix: 3 Queries
# Nach Fix: 1 Query → 3× schneller!
```

**Status:** ⬜ TODO

---

### 🐌 PERFORMANCE #12: Missing Database Indexes
**Priorität:** P2 (MEDIUM)
**Impact:** Langsame Queries bei vielen Pages (>10k)
**Geschätzte Zeit:** 15 Minuten
**Dateien:** `supabase_schema.sql:60-64`

**Problem:**
- Fehlende Indexes für häufige Queries
- `ORDER BY created_at` ohne Index → Full Table Scan

**Lösung:**
```sql
-- In Supabase SQL Editor ausführen:

-- Für get_previous_snapshot_map() - ORDER BY created_at
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_created
ON snapshots(competitor_id, created_at DESC);

-- Für canonical_url Lookups (Change Detection)
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url
ON pages(snapshot_id, canonical_url);

-- Für sha256_text Lookups (Duplikat-Erkennung)
CREATE INDEX IF NOT EXISTS idx_pages_sha256
ON pages(sha256_text);

-- Für Profile-Queries
CREATE INDEX IF NOT EXISTS idx_profiles_snapshot
ON profiles(snapshot_id);

-- Für Social Links Queries
CREATE INDEX IF NOT EXISTS idx_socials_platform
ON socials(competitor_id, platform);

-- Prüfe Index-Nutzung
EXPLAIN ANALYZE
SELECT * FROM snapshots
WHERE competitor_id = 'xxx'
ORDER BY created_at DESC
LIMIT 1;
```

**Status:** ⬜ TODO

---

## 🔵 LOW - Nice to have

### ⚠️ BUG #13: Fehlende Foreign Key Constraints für prev_page_id
**Priorität:** P3 (LOW)
**Impact:** Dangling References möglich
**Geschätzte Zeit:** 15 Minuten
**Dateien:** `supabase_schema.sql`

**Lösung:**
```sql
ALTER TABLE pages
ADD CONSTRAINT fk_prev_page
FOREIGN KEY (prev_page_id)
REFERENCES pages(id)
ON DELETE SET NULL;
```

**Status:** ⬜ TODO

---

### 🔒 SECURITY #18: Ungeschützte Download-Endpoints
**Priorität:** P3 (LOW)
**Impact:** Jeder mit page_id kann Daten downloaden
**Geschätzte Zeit:** 1 Stunde
**Dateien:** `backend/main.py:605-685`

**Lösung:**
```python
# backend/main.py
@app.get("/api/pages/{page_id}/raw")
async def download_raw(
    page_id: str,
    api_key: str = Header(None, alias="X-API-Key")
):
    # API Key Validation
    expected_key = os.getenv("API_SECRET_KEY")
    if not expected_key or api_key != expected_key:
        raise HTTPException(401, "Unauthorized")

    # ... rest
```

**Status:** ⬜ TODO

---

## 📊 FORTSCHRITT

**CRITICAL:** 0/4 behoben (0%)
**HIGH:** 0/4 behoben (0%)
**MEDIUM:** 0/7 behoben (0%)
**LOW:** 0/2 behoben (0%)

**Gesamt:** 0/17 behoben (0%)

---

## ⏱️ ZEITSCHÄTZUNG

**CRITICAL (BLOCKER):** 2.5 Stunden
**HIGH:** 3 Stunden
**MEDIUM:** 5 Stunden
**LOW:** 1.5 Stunden

**Gesamt:** ~12 Stunden für produktionsreife Version

---

## 🚀 DEPLOYMENT-CHECKLIST

Vor Production-Deployment MÜSSEN diese behoben sein:

- [ ] BUG #5: SQL Schema Update
- [ ] BUG #6: Duplicate Policies
- [ ] BUG #14: Storage Bucket Fix
- [ ] SECURITY #15: SSRF Protection
- [ ] SECURITY #16: CORS Configuration
- [ ] SECURITY #17: Rate Limiting

**Status:** ⚠️ NICHT PRODUCTION-READY

---

## 📝 NOTIZEN

- Alle Fixes sind rückwärtskompatibel (außer Schema-Änderungen)
- Migrations sollten in `migrations/` Ordner dokumentiert werden
- Nach jedem Fix: Tests durchführen (siehe jeweilige "Testen"-Sektion)
- Frontend-Fixes erfordern Rebuild: `npm run build`
- Backend-Fixes erfordern Server-Restart

**Letztes Update:** 2025-12-27 15:45 UTC
