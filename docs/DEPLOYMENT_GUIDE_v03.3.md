# 🚀 DEPLOYMENT GUIDE v03.3

**Version:** v03.3 (Critical Fixes)
**Datum:** 2025-12-27
**Voraussetzung:** v03.2 deployed auf Railway + Vercel

---

## ⚠️ WICHTIG: VOR DEM DEPLOYMENT

Dieser Release behebt **4 CRITICAL Bugs**. Ohne diese Fixes ist die App **NICHT FUNKTIONSFÄHIG**!

**Was wurde behoben:**
1. ✅ SQL Schema Mismatch → Pages können gespeichert werden
2. ✅ Storage Bucket Fix → Files können hochgeladen werden
3. ✅ SSRF Protection → Security-Hole geschlossen
4. ✅ Duplicate Policies → SQL Script ist ausführbar

---

## 📋 DEPLOYMENT SCHRITTE

### SCHRITT 1: Supabase Migration (CRITICAL!)

**Dauer:** 5 Minuten

1. **Öffne Supabase Dashboard**
   - Gehe zu: https://supabase.com/dashboard
   - Wähle dein Projekt: `simplecomptool-prod`

2. **Öffne SQL Editor**
   - Linke Sidebar → SQL Editor
   - Click: New Query

3. **Run Migration**
   - Kopiere kompletten Inhalt aus: `migrations/001_add_missing_columns.sql`
   - Paste in SQL Editor
   - Click: Run (Ctrl+Enter)

4. **Prüfe Output**
   ```sql
   -- Sollte zeigen:
   -- ALTER TABLE (für jede Spalte)
   -- CREATE INDEX (für jeden Index)
   -- SELECT (Spalten-Liste)
   ```

5. **Verify**
   ```sql
   -- Prüfe dass alle Spalten existieren:
   SELECT column_name, data_type
   FROM information_schema.columns
   WHERE table_name = 'pages'
   ORDER BY column_name;

   -- Erwartung:
   -- canonical_url, changed, prev_page_id, text_length,
   -- normalized_len, has_truncation, extraction_version, fetch_duration
   -- sollten alle vorhanden sein
   ```

✅ **Checkpoint:** Alle 8 neuen Spalten existieren

---

### SCHRITT 2: Storage Bucket Check

**Dauer:** 2 Minuten

1. **Öffne Storage**
   - Supabase Dashboard → Storage

2. **Prüfe Buckets**
   - Sollte existieren: `snapshots` (private)
   - Falls nicht: Click "New Bucket"
     - Name: `snapshots`
     - Public: NO (unchecked)
     - Click: Create

3. **Optional: Alte Buckets löschen**
   - Falls `html-files` oder `txt-files` existieren → Können gelöscht werden
   - Diese werden nicht mehr verwendet

✅ **Checkpoint:** Bucket `snapshots` existiert

---

### SCHRITT 3: Backend Deployment

**Dauer:** 3-5 Minuten

1. **Git Push**
   ```bash
   cd simple-comptool-v3
   git add .
   git commit -m "v03.3: Fix critical bugs (SQL schema, storage, SSRF)"
   git push origin main
   ```

2. **Railway Auto-Deploy**
   - Railway Dashboard → Service
   - Deployment startet automatisch
   - Warte auf: "Deployed" Status (~2-3 Min)

3. **Prüfe Logs**
   - Railway → Deployments → Latest → View Logs
   - Suche nach:
     ```
     ✅ Bucket 'snapshots' erstellt
     # oder
     ✅ Bucket 'snapshots' existiert bereits
     ```

4. **Health Check**
   ```bash
   curl https://your-backend.up.railway.app/health/ready
   # Erwartung: {"status":"ready", ...}
   ```

✅ **Checkpoint:** Backend läuft ohne Errors

---

### SCHRITT 4: SSRF Protection Test

**Dauer:** 2 Minuten

1. **Run Test Script**
   ```bash
   # Lokal:
   export API_URL=https://your-backend.up.railway.app
   ./test_ssrf_protection.sh
   ```

2. **Erwartete Outputs**
   ```
   Test 1: LOCALHOST_NOT_ALLOWED
   Test 2: LOCALHOST_NOT_ALLOWED
   Test 3: METADATA_SERVICE_BLOCKED
   Test 4: PRIVATE_IP_NOT_ALLOWED
   Test 5: PRIVATE_IP_NOT_ALLOWED
   Test 6: INVALID_URL_SCHEME
   Test 7: true (scan starts)
   ```

3. **Falls Tests fehlschlagen:**
   - Prüfe Railway Logs
   - Prüfe ob `validators.py` deployed wurde
   - Restart Backend

✅ **Checkpoint:** SSRF Tests erfolgreich

---

### SCHRITT 5: Functional Test

**Dauer:** 5 Minuten

1. **Öffne Frontend**
   - https://your-app.vercel.app

2. **Test Scan**
   - Eingabe: `example.com`
   - Click: Scan starten
   - Warte auf Completion

3. **Prüfe Backend Logs**
   - Railway → Logs
   - Suche nach:
     ```
     [scan_id] Scan gestartet für URL: https://example.com
     [scan_id] Discovery abgeschlossen: X URLs gefunden
     [scan_id] Page gespeichert: page_id
     [scan_id] Scan erfolgreich abgeschlossen
     ```
   - ❌ NICHT da sein sollte: `column "canonical_url" does not exist`

4. **Prüfe Results Page**
   - Frontend sollte redirecten zu: `/results/{snapshot_id}`
   - Pages sollten angezeigt werden
   - Changed/Unchanged Status sichtbar

5. **Prüfe Supabase Storage**
   - Supabase → Storage → snapshots
   - Sollte neue Folders sehen: `{snapshot_id}/pages/`
   - Files: `{page_id}.html`, `{page_id}.txt`

6. **Test Downloads**
   - Results Page → Click "HTML" Link
   - Sollte HTML-Content zeigen
   - Click "Text" Link
   - Sollte Text-Content zeigen

✅ **Checkpoint:** Kompletter Flow funktioniert

---

### SCHRITT 6: Smoke Tests

**Dauer:** 3 Minuten

1. **Test verschiedene URLs**
   ```
   ✅ https://example.com (sollte funktionieren)
   ✅ bild.de (ohne https://) (sollte funktionieren)
   ❌ localhost:8000 (sollte blockiert werden)
   ❌ 192.168.1.1 (sollte blockiert werden)
   ```

2. **Test Error Handling**
   - Eingabe: Ungültige URL (z.B. `asdf`)
   - Erwartung: Klare Fehlermeldung

3. **Test Parallel Scans**
   - Starte 2 Scans gleichzeitig (2 Browser Tabs)
   - Beide sollten funktionieren
   - Prüfe Logs: Concurrency funktioniert

✅ **Checkpoint:** Alle Edge Cases funktionieren

---

## 🚨 TROUBLESHOOTING

### Problem: "column does not exist" Error

**Symptom:** Backend Logs zeigen `column "canonical_url" does not exist`

**Lösung:**
1. Prüfe ob Migration ausgeführt wurde:
   ```sql
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'pages' AND column_name = 'canonical_url';
   ```
2. Falls leer → Run Migration nochmal
3. Backend Restart

---

### Problem: "Bucket not found" Error

**Symptom:** Backend Logs zeigen `Bucket not found: snapshots`

**Lösung:**
1. Supabase Dashboard → Storage
2. Create Bucket: `snapshots` (private)
3. Backend Restart

---

### Problem: SSRF Tests schlagen NICHT fehl

**Symptom:** `localhost` wird NICHT blockiert

**Lösung:**
1. Prüfe ob `validators.py` deployed wurde:
   ```bash
   # In Railway Console:
   ls backend/validators.py
   ```
2. Prüfe Import in `main.py`:
   ```python
   from validators import validate_scan_url
   ```
3. Backend Restart

---

### Problem: Files werden nicht gespeichert

**Symptom:** Storage bleibt leer nach Scan

**Lösung:**
1. Prüfe Railway Logs für Storage Errors
2. Prüfe Supabase → Storage → Buckets → "snapshots" existiert
3. Prüfe ENV Variables:
   - `SUPABASE_URL` korrekt?
   - `SERVICE_ROLE_KEY` korrekt?

---

## ✅ DEPLOYMENT CHECKLIST

- [ ] Migration `001_add_missing_columns.sql` ausgeführt
- [ ] 8 neue Spalten in `pages` Tabelle vorhanden
- [ ] Bucket `snapshots` existiert in Supabase Storage
- [ ] Backend auf Railway deployed (v03.3)
- [ ] Backend Logs zeigen keine Errors
- [ ] SSRF Tests bestehen (alle blockiert außer example.com)
- [ ] Test Scan funktioniert (example.com)
- [ ] Pages werden in DB gespeichert
- [ ] Files erscheinen in Storage
- [ ] Results Page zeigt Daten
- [ ] Downloads funktionieren (HTML + Text)

---

## 🎉 SUCCESS CRITERIA

Deployment ist erfolgreich wenn:

1. ✅ Test Scan läuft ohne DB Errors
2. ✅ Files werden in Supabase Storage gespeichert
3. ✅ SSRF Protection blockiert gefährliche URLs
4. ✅ Results Page zeigt korrekte Daten
5. ✅ Downloads funktionieren

**Status:** 🚀 **PRODUCTION-READY!**

---

## 📊 ROLLBACK (Falls nötig)

Falls kritische Probleme auftreten:

1. **Backend Rollback:**
   ```bash
   # In Railway Dashboard:
   Deployments → Previous Version (v03.2) → Redeploy
   ```

2. **DB Rollback:**
   ```sql
   -- Optional: Entferne neue Spalten
   ALTER TABLE pages DROP COLUMN IF EXISTS canonical_url;
   ALTER TABLE pages DROP COLUMN IF EXISTS changed;
   -- etc.
   ```

3. **Storage Rollback:**
   - Bucket `snapshots` kann bleiben
   - Alte Buckets wieder erstellen falls gelöscht

---

## 📞 SUPPORT

Bei Problemen:
1. Check Railway Logs
2. Check Supabase Logs
3. Check Browser Console (Frontend)
4. Review: `docs/CRITICAL_FIXES_v03.3.md`

---

**Happy Deploying! 🚀**

*Erstellt am 2025-12-27*
