# 🐛 BUGFIX TODO - Simple CompTool v3.2 (UPDATED)

**Letzte Aktualisierung:** 2025-12-27 (Nach Review der Commit-History)
**Basis:** Commit `de104f8` - v03.2 ✅ Deploy!
**Status:** Nach Abgleich mit bereits behobenen Bugs

---

## ✅ BEREITS BEHOBEN (Commits v03.1 - v03.2)

Die folgenden Bugs aus meiner ursprünglichen Analyse wurden **BEREITS VON DIR BEHOBEN**:

### ✅ P0 - Kritische Bugs (ALLE BEHOBEN!)
1. **BUG #1: Race Condition in Browser Manager** → ✅ Behoben in v03.1.1
2. **BUG #2: Memory Leak - Zombie Chromium** → ✅ Behoben in v03.1.1 (Shutdown Event)
3. **BUG #7: Async/Sync Mix in LLM** → ✅ Nicht mehr relevant (Text bereits im Memory)
4. **Performance: Browser Lock** → ✅ Behoben in v03.1.1

### ✅ P1 - High Priority (TEILWEISE BEHOBEN)
5. **CORS Security** → ✅ Behoben in v03.1.1 (Wildcard-Check)
6. **URL Normalization** → ✅ Behoben in v03.1.1 (utils/url_utils.py)
7. **Text Extraction 50k Limit** → ✅ Behoben in v03.1 (extract_text_from_html_v2)
8. **Change Detection** → ✅ Behoben in v03.1 (Hash-Gate)
9. **Logger Initialization** → ✅ Behoben in 6e9963e
10. **Health Check Endpoints** → ✅ Behoben in c386818
11. **Frontend Error Handling** → ✅ Teilweise behoben (Timeout in page.tsx)

---

## 🚨 CRITICAL - NOCH ZU BEHEBEN

### ⚠️ BUG #5: SQL Schema vs. Code Mismatch
**Priorität:** P0 (BLOCKER)
**Impact:** **Alle Page-Saves schlagen wahrscheinlich fehl**
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
Der Code in `persistence.py:407-414` speichert Felder, die im SQL Schema fehlen:
- `canonical_url`
- `changed`
- `prev_page_id`
- `text_length`
- `normalized_len`
- `has_truncation`
- `extraction_version`
- `fetch_duration`

**Kritischer Test:**
```bash
# Teste ob Save funktioniert
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Prüfe Logs auf DB-Fehler:
# ERROR: column "canonical_url" of relation "pages" does not exist
```

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

-- Indexes für Performance
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(snapshot_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_created ON snapshots(competitor_id, created_at DESC);
```

**Verifikation:**
```sql
-- Prüfe dass alle Spalten existieren
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'pages';
```

---

### ⚠️ BUG #6: Duplicate Policy Names in SQL Schema
**Priorität:** P0 (BLOCKER für neue Deployments)
**Impact:** SQL Schema kann nicht ausgeführt werden
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
`supabase_schema.sql:73-78` hat 5 Policies mit identischem Namen:
```sql
CREATE POLICY "Allow all operations for anon" ON competitors ...
CREATE POLICY "Allow all operations for anon" ON snapshots ...  -- ERROR!
```

**Lösung:**
```sql
-- In supabase_schema.sql ändern:
DROP POLICY IF EXISTS "Allow all operations for anon" ON competitors;
DROP POLICY IF EXISTS "Allow all operations for anon" ON snapshots;
DROP POLICY IF EXISTS "Allow all operations for anon" ON pages;
DROP POLICY IF EXISTS "Allow all operations for anon" ON socials;
DROP POLICY IF EXISTS "Allow all operations for anon" ON profiles;

CREATE POLICY "Allow all for anon on competitors" ON competitors FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on snapshots" ON snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on pages" ON pages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on socials" ON socials FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon on profiles" ON profiles FOR ALL USING (true) WITH CHECK (true);
```

---

### ⚠️ BUG #14: Storage Bucket Name Mismatch
**Priorität:** P0 (BLOCKER)
**Impact:** **Alle File-Uploads schlagen fehl**
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
- `init_db()` erstellt Buckets: `html-files`, `txt-files` (persistence.py:81-99)
- `save_page()` uploaded in Bucket: `snapshots` (persistence.py:335-346)
- **Bucket "snapshots" existiert nicht!**

**Kritischer Test:**
```python
# Prüfe in Supabase Dashboard:
# Storage > Buckets > Welche Buckets existieren?
# Erwartung: "snapshots" sollte existieren, aber existiert es?
```

**Lösung Option A (Empfohlen - Ein Bucket):**
```python
# backend/services/persistence.py

def init_db():
    # ...
    try:
        # ✅ Einen gemeinsamen Bucket für alles
        admin_client.storage.create_bucket("snapshots")
        logger.info("Bucket 'snapshots' erstellt")
    except Exception as e:
        error_str = str(e).lower()
        if "already exists" in error_str or "duplicate" in error_str:
            logger.info("Bucket 'snapshots' existiert bereits")
        else:
            logger.warning(f"Fehler beim Erstellen des Snapshots-Buckets: {e}")

# save_page() bleibt unverändert (nutzt bereits 'snapshots')
```

**Oder manuell in Supabase:**
```
Supabase Dashboard → Storage → Create Bucket
Name: snapshots
Public: NO (private)
```

---

### 🔒 SECURITY #15: SSRF Vulnerability
**Priorität:** P0 (SECURITY CRITICAL)
**Impact:** Server kann interne Services/Metadata angreifen
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
Keine Validierung von URLs in `/api/scan`:
```python
# User kann eingeben:
{"url": "http://localhost:8000/admin"}  # SSRF
{"url": "http://169.254.169.254/latest/meta-data/"}  # AWS Metadata
```

**Lösung:**
```python
# backend/validators.py (NEU erstellen)
from fastapi import HTTPException
import re
from urllib.parse import urlparse

PRIVATE_IP_REGEX = r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.)'
AWS_METADATA_IP = '169.254.169.254'

def validate_scan_url(url: str) -> str:
    """Validates URL for Scan requests - SSRF Protection"""

    # Length check
    if not url or len(url) > 2048:
        raise HTTPException(400, detail="URL muss zwischen 1-2048 Zeichen sein")

    url = url.strip()

    # Parse
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(400, detail="Ungültiges URL-Format")

    # Schema validation
    if parsed.scheme and parsed.scheme not in ['http', 'https']:
        raise HTTPException(400, detail=f"Ungültiges Schema: {parsed.scheme}")

    # SSRF Protection
    if parsed.hostname:
        hostname = parsed.hostname.lower()

        # Localhost
        if hostname in ['localhost', '0.0.0.0', '::1', '127.0.0.1']:
            raise HTTPException(400, detail="Localhost nicht erlaubt")

        # AWS Metadata
        if hostname == AWS_METADATA_IP:
            raise HTTPException(400, detail="Metadata-Service nicht erlaubt")

        # Private IPs
        if re.match(PRIVATE_IP_REGEX, hostname):
            raise HTTPException(400, detail="Private IPs nicht erlaubt")

    return url

# backend/main.py
from validators import validate_scan_url

@app.post("/api/scan", response_model=ScanResponse)
async def scan_endpoint(request: ScanRequest):
    request.url = validate_scan_url(request.url)  # ✅ VALIDATE!
    # ... rest
```

**Test:**
```bash
# Sollte blockiert werden:
curl -X POST http://localhost:8000/api/scan -d '{"url":"http://localhost:8000"}'
# Erwartung: HTTP 400 "Localhost nicht erlaubt"

curl -X POST http://localhost:8000/api/scan -d '{"url":"http://169.254.169.254"}'
# Erwartung: HTTP 400 "Metadata-Service nicht erlaubt"
```

---

## 🔴 HIGH - Diese Woche

### ⚠️ BUG #1: Race Condition in get_previous_snapshot_map()
**Priorität:** P1 (HIGH)
**Impact:** Inkorrekte Change Detection bei parallelen Scans
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
Zwei parallele Scans für denselben Competitor:
1. Scan 1: `get_previous_snapshot_map()` → lädt Snapshot A
2. Scan 1: `create_snapshot()` → erstellt Snapshot B
3. Scan 2: `get_previous_snapshot_map()` → lädt **Snapshot A** (sollte B sein!)
4. Result: Scan 2 markiert alles als "changed" obwohl Scan 1 gerade gespeichert hat

**Lösung:**
```python
# backend/services/persistence.py
async def get_previous_snapshot_map(
    competitor_id: str,
    exclude_snapshot_id: Optional[str] = None  # ✅ NEU
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
    # ... rest

# backend/main.py - REIHENFOLGE ÄNDERN
snapshot_id = create_snapshot(competitor_id)  # ✅ Erst erstellen
prev_map = await get_previous_snapshot_map(
    competitor_id,
    exclude_snapshot_id=snapshot_id  # ✅ Dann laden mit Exclude
)
```

---

### 🔒 SECURITY #16: CORS Production Fallback
**Priorität:** P1 (HIGH)
**Impact:** Production-Fehler wenn CORS_ORIGINS nicht gesetzt
**Status:** ⚠️ **TEILWEISE BEHOBEN** (Wildcard-Check vorhanden, aber Production-Check fehlt)

**Problem:**
Aktuell in `main.py:28-59`:
```python
origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")  # ⚠️ Fallback auf localhost
```

In Production ohne `CORS_ORIGINS` → Fallback auf localhost → Frontend kann nicht zugreifen!

**Lösung:**
```python
def _get_cors_origins() -> List[str]:
    origins_str = os.getenv("CORS_ORIGINS")

    # Check Production
    is_production = bool(
        os.getenv("RAILWAY_ENVIRONMENT") or
        os.getenv("VERCEL") or
        os.getenv("PRODUCTION")
    )

    # Production: REQUIRED
    if not origins_str:
        if is_production:
            raise ValueError(
                "❌ CORS_ORIGINS muss in Production gesetzt sein!\n"
                "Beispiel: CORS_ORIGINS=https://myapp.vercel.app"
            )
        else:
            return ["http://localhost:3000"]  # Dev Fallback

    # ... rest (Wildcard-Check bleibt)
```

---

### 🔒 SECURITY #17: Missing Rate Limiting
**Priorität:** P1 (HIGH)
**Impact:** DoS-Attacken möglich
**Status:** ⚠️ **NICHT BEHOBEN**

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

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/scan")
@limiter.limit("5/minute")  # Max 5 Scans pro Minute
async def scan_endpoint(request: Request, scan_request: ScanRequest):
    # ...
```

---

### ⚠️ BUG #2: Storage Path Inconsistenz
**Priorität:** P1 (HIGH)
**Impact:** Downloads schlagen fehl bei lokalem Fallback
**Status:** ⚠️ **NICHT BEHOBEN**

**Problem:**
`main.py:626-638`:
```python
local_path = os.path.join("backend/data/snapshots", raw_path)
# raw_path ist: "{snapshot_id}/pages/{page_id}.html"
# Resultat: "backend/data/snapshots/{snapshot_id}/pages/{page_id}.html"
# Aber Files liegen in Supabase Storage!
```

**Lösung (Empfohlen): Entferne lokalen Fallback**
```python
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

        # Nur Supabase Storage (kein lokaler Fallback)
        file_data = supabase.storage.from_("snapshots").download(page_result.data['raw_path'])
        return Response(content=file_data, media_type="text/html; charset=utf-8")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(500, "Download fehlgeschlagen")
```

---

## 🟡 MEDIUM - Nice to have

### 🐌 PERFORMANCE #11: N+1 Query Problem
**Priorität:** P2 (MEDIUM)
**Impact:** 3× DB-Queries statt 1 für Competitor
**Status:** ⚠️ **NICHT BEHOBEN**

**Lösung:**
```python
def get_competitor(competitor_id: str) -> Optional[dict]:
    # ✅ Alles in 1 Query mit JOIN
    result = supabase.table('competitors').select('''
        *,
        snapshots(id, created_at, page_count, notes),
        socials(platform, handle, url)
    ''').eq('id', competitor_id).single().execute()

    return result.data
```

---

### 🐌 PERFORMANCE #12: Missing Indexes
**Priorität:** P2 (MEDIUM)
**Impact:** Langsame Queries bei vielen Pages
**Status:** ⚠️ **NICHT BEHOBEN**

**Lösung:**
```sql
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_created ON snapshots(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(snapshot_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_pages_sha256 ON pages(sha256_text);
CREATE INDEX IF NOT EXISTS idx_profiles_snapshot ON profiles(snapshot_id);
```

---

## 📊 AKTUALISIERTER STATUS

**BEREITS BEHOBEN:** 11/29 Bugs (38%)
- ✅ Alle P0 Performance-Bugs (Browser Lock, Memory Leak)
- ✅ CORS Wildcard Security
- ✅ URL Normalization
- ✅ Text Extraction
- ✅ Change Detection
- ✅ Frontend Error Handling (teilweise)

**NOCH ZU BEHEBEN:** 18/29 Bugs (62%)

### CRITICAL (BLOCKER für Production):
- [ ] BUG #5: SQL Schema Mismatch
- [ ] BUG #6: Duplicate Policies
- [ ] BUG #14: Storage Bucket Mismatch
- [ ] SECURITY #15: SSRF Protection

### HIGH (Diese Woche):
- [ ] BUG #1: Race Condition Snapshots
- [ ] SECURITY #16: CORS Production Check
- [ ] SECURITY #17: Rate Limiting
- [ ] BUG #2: Storage Path Fix

### MEDIUM (Nice to have):
- [ ] Performance #11: N+1 Queries
- [ ] Performance #12: Missing Indexes
- [ ] + weitere aus ursprünglicher Liste

---

## ⏱️ ZEITSCHÄTZUNG (UPDATED)

**CRITICAL (4 Bugs):** 2 Stunden
**HIGH (4 Bugs):** 2.5 Stunden
**MEDIUM (2 Bugs):** 1 Stunde

**Gesamt:** ~5.5 Stunden für Production-Ready

---

## 🚀 NÄCHSTE SCHRITTE

1. **SOFORT (30 min):**
   - [ ] SQL Schema Update (BUG #5)
   - [ ] Storage Bucket Fix (BUG #14)

2. **HEUTE (1.5 Stunden):**
   - [ ] SSRF Protection (SECURITY #15)
   - [ ] Duplicate Policies Fix (BUG #6)

3. **DIESE WOCHE (2.5 Stunden):**
   - [ ] Rate Limiting (SECURITY #17)
   - [ ] CORS Production Check (SECURITY #16)
   - [ ] Race Condition Fix (BUG #1)
   - [ ] Storage Path Fix (BUG #2)

---

## 📝 FAZIT

**Großartige Arbeit!** Du hast bereits 38% der Bugs behoben, inklusive aller kritischen Performance-Killer!

**Verbleibende Blocker sind primär:**
1. **Datenbank-Setup** (Schema + Buckets) → 30 Minuten
2. **Security** (SSRF, Rate Limiting) → 2 Stunden
3. **Edge Cases** (Race Conditions, Storage) → 1.5 Stunden

**Status:** ⚠️ **NOCH NICHT PRODUCTION-READY** (4 CRITICAL Bugs)

Nach den CRITICAL Fixes → **READY FOR DEPLOYMENT** 🚀
