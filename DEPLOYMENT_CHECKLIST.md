# 🚀 Deployment Checklist - Simple CompTool

## ✅ PRE-DEPLOYMENT (LOKAL ERLEDIGT)

- [x] Backend Port-Fix implementiert
- [x] ENV-Validation Code hinzugefügt
- [x] Health Check Endpoints erstellt
- [x] Dockerfile erstellt
- [x] Railway.json konfiguriert
- [x] Frontend .env.example erstellt
- [x] Vercel.json konfiguriert
- [x] Git Commits gemacht

---

## 🔴 PHASE 1: SUPABASE SETUP (VOR RAILWAY)

### 1.1 Projekt erstellen
- [ ] Supabase Dashboard → New Project
- [ ] Projekt-Name: `simplecomptool-prod`
- [ ] Region: Closest to you (z.B. Frankfurt)
- [ ] Database Password: Sicher speichern!

### 1.2 Database Schema
- [ ] Supabase Dashboard → SQL Editor
- [ ] Führe `backend/supabase_schema.sql` aus
- [ ] Prüfe: Tables `competitors`, `snapshots`, `pages`, `socials`, `profiles` existieren

### 1.3 Storage Setup
- [ ] Supabase Dashboard → Storage → Create Bucket
- [ ] Bucket Name: `snapshots`
- [ ] Public: NO (private)
- [ ] Führe `backend/supabase_storage_policies.sql` aus (SQL Editor)

### 1.4 Keys sammeln
- [ ] Settings → API → Copy:
  - `SUPABASE_URL`: https://xxx.supabase.co
  - `SUPABASE_SERVICE_ROLE_KEY`: eyJhbG... (SERVICE ROLE, nicht ANON!)

---

## 🟡 PHASE 2: RAILWAY DEPLOYMENT (BACKEND)

### 2.1 Repository verbinden
- [ ] Railway Dashboard → New Project
- [ ] Deploy from GitHub Repo
- [ ] Select Repository: `your-username/simple-comptool`

### 2.2 Service konfigurieren
- [ ] Root Directory: `backend`
- [ ] Railway erkennt Dockerfile automatisch ✅

### 2.3 Environment Variables setzen

**WICHTIG:** Alle kopieren und in Railway einfügen!
```env
ENVIRONMENT=production
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...
SUPABASE_STORAGE_BUCKET=snapshots
CORS_ORIGINS=http://localhost:3000
GLOBAL_SCAN_TIMEOUT=300
MAX_PAGES=20
```

**Optional (wenn LLM genutzt):**
```env
OPENAI_API_KEY=sk-...
```

**WICHTIG:** `CORS_ORIGINS` wird später auf Vercel-URL geändert!

### 2.4 Deploy starten
- [ ] Railway → Deploy
- [ ] Warte auf Build (~3-5 Min wegen Playwright)
- [ ] Prüfe Logs: "Starting server on port ..."

### 2.5 Health Check testen
- [ ] Railway Dashboard → Service → Domain → Copy URL
- [ ] Teste: `curl https://your-backend.up.railway.app/health`
- [ ] Erwartung: `{"status":"healthy",...}`
- [ ] Teste: `curl https://your-backend.up.railway.app/health/ready`
- [ ] Erwartung: `{"status":"ready","checks":{"database":true,"storage":true}}`

**WENN NICHT "ready":** Prüfe ENV-Variablen (Supabase Keys korrekt?)

### 2.6 Railway URL speichern
- [ ] Kopiere: `https://your-backend.up.railway.app`
- [ ] Brauchen wir für Vercel!

---

## 🟢 PHASE 3: VERCEL DEPLOYMENT (FRONTEND)

### 3.1 Repository importieren
- [ ] Vercel Dashboard → Add New Project
- [ ] Import Git Repository
- [ ] Select: `your-username/simple-comptool`

### 3.2 Build Settings
- [ ] Framework Preset: `Next.js` (auto-detected ✅)
- [ ] Root Directory: `frontend`
- [ ] Build Command: (leer lassen, nutzt package.json)
- [ ] Output Directory: (leer lassen, nutzt .next)

### 3.3 Environment Variables

**WICHTIG:** Railway URL von Phase 2 einfügen!
```env
NEXT_PUBLIC_API_URL=https://your-backend.up.railway.app
```

### 3.4 Deploy starten
- [ ] Vercel → Deploy
- [ ] Warte auf Build (~2 Min)
- [ ] Prüfe: Deployment successful

### 3.5 Frontend testen
- [ ] Vercel Dashboard → Deployment → Visit
- [ ] Landing Page lädt? ✅
- [ ] Browser Console: CORS Errors? (Normal, fix kommt in Phase 4)

### 3.6 Vercel URL speichern
- [ ] Kopiere: `https://your-app.vercel.app`
- [ ] Brauchen wir für CORS-Fix!

---

## 🔵 PHASE 4: CORS FINALISIEREN

### 4.1 CORS Origins aktualisieren
- [ ] Railway Dashboard → Service → Variables
- [ ] Finde `CORS_ORIGINS`
- [ ] Ändere zu: `https://your-app.vercel.app` (Vercel URL von Phase 3!)
- [ ] Save → Railway redeploys automatisch

### 4.2 Warte auf Redeploy
- [ ] Railway → Deployments → Warte auf "Deployed"
- [ ] ~2 Min

### 4.3 CORS testen
- [ ] Vercel Frontend neu laden (F5)
- [ ] Browser Console → Network Tab
- [ ] Scan starten (URL eingeben)
- [ ] Prüfe: Kein CORS Error ✅
- [ ] Request zu Railway erfolgreich ✅

---

## 🎯 PHASE 5: SMOKE TESTS

### 5.1 Full Scan Flow
- [ ] Frontend: URL eingeben (z.B. `https://example.com`)
- [ ] Scan starten
- [ ] Warte auf Completion
- [ ] Results Page lädt ✅
- [ ] Pages werden angezeigt ✅
- [ ] Download Links funktionieren ✅

### 5.2 Supabase Daten prüfen
- [ ] Supabase → Table Editor → `snapshots`
- [ ] Neuer Eintrag vorhanden? ✅
- [ ] Supabase → Storage → `snapshots`
- [ ] Neue Files vorhanden? (z.B. `snapshots/xxx/pages/yyy.html`) ✅

### 5.3 Railway Logs prüfen
- [ ] Railway → Service → Logs
- [ ] Keine Errors ✅
- [ ] "Starting server on port ..." ✅
- [ ] "Scan completed" oder ähnlich ✅

---

## ✅ DEPLOYMENT ERFOLGREICH!

**Backend:** https://your-backend.up.railway.app
**Frontend:** https://your-app.vercel.app

---

## 🔧 TROUBLESHOOTING

### Railway Build schlägt fehl
1. Prüfe Logs: Railway → Service → Deployments → Failed → View Logs
2. Häufige Fehler:
   - Playwright Installation: `playwright install chromium` in Dockerfile
   - Port nicht gesetzt: ENV-Variable `PORT` fehlt (Railway setzt das automatisch)

### Health Check "not_ready"
1. Prüfe ENV-Variablen: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
2. Teste manuell: `curl https://your-backend.up.railway.app/health/ready`
3. Prüfe Logs für Details

### CORS Errors
1. Prüfe `CORS_ORIGINS` in Railway: Muss EXAKT Vercel URL sein
2. Prüfe Frontend: `NEXT_PUBLIC_API_URL` muss Railway URL sein
3. Beide Services neu deployen

### Frontend lädt nicht
1. Prüfe Vercel Logs: Vercel → Deployments → Failed → Logs
2. Häufige Fehler:
   - `NEXT_PUBLIC_API_URL` nicht gesetzt
   - Build Error: `npm run build` lokal testen

### Scan funktioniert nicht
1. Prüfe Railway Logs während Scan
2. Teste Health Check
3. Prüfe Supabase Connection (Logs)
````

