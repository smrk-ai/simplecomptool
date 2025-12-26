# 🔧 Dependency-Konflikt Lösung

## Problem

Der ursprüngliche Konflikt zwischen `httpx==0.28.1` und `supabase==2.10.0` wurde behoben.

## ✅ Lösung

Die `requirements.txt` wurde angepasst:

```diff
- supabase==2.10.0
+ supabase>=2.10.0,<3.0.0
```

Dies erlaubt pip, eine kompatible Supabase-Version automatisch auszuwählen.

## 📦 Installation

### Option 1: Nur SQLite (EMPFOHLEN für lokale Entwicklung)

Wenn Sie **nur SQLite** verwenden:

```bash
cd backend
pip install -r requirements.txt --no-deps
pip install fastapi uvicorn pydantic playwright aiosqlite httpx beautifulsoup4 lxml openai python-dotenv slowapi
```

### Option 2: Mit Supabase (für Cloud-Deployment)

Wenn Sie **Supabase** verwenden möchten:

```bash
cd backend
pip install --upgrade pip  # Empfohlen: pip auf neueste Version
pip install -r requirements.txt
```

**Hinweis:** Dies installiert die neueste kompatible Supabase-Version (2.27.0+).

## 🔍 Überprüfung

Testen Sie die Installation:

```bash
python3 -c "from main import app; print('✅ Backend funktioniert!')"
```

## 🎯 Verwendung

### Nur SQLite (Standard)

Keine zusätzliche Konfiguration erforderlich. Der Server verwendet automatisch SQLite.

```bash
python3 -m uvicorn main:app --reload
```

### Mit Supabase

Setzen Sie diese Umgebungsvariablen in `.env.local`:

```env
PERSISTENCE_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_STORAGE_BUCKET=snapshots
PUBLIC_BASE_URL=https://your-app.com
```

## ⚠️ Bekannte Einschränkungen

1. **Python 3.9 erforderlich:** Die neueste Supabase-Version benötigt Python 3.9+
2. **Websockets:** Bei Supabase wird `websockets>=13.0` benötigt für Realtime-Features

## 🆘 Troubleshooting

### Fehler: "ModuleNotFoundError: No module named 'websockets.asyncio'"

```bash
pip install --upgrade websockets
```

### Fehler: "ResolutionImpossible: conflicting dependencies"

Lösung: Verwenden Sie einen Virtual Environment:

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# oder
venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### Supabase nicht benötigt?

Entfernen Sie Supabase aus `requirements.txt`, wenn Sie es nicht nutzen:

```bash
# Editieren Sie requirements.txt und entfernen Sie die Zeile:
# supabase>=2.10.0,<3.0.0
```

## ✅ Status

- ✅ SQLite-Backend: **Funktioniert einwandfrei**
- ✅ Supabase-Backend: **Funktioniert mit neuerer Version**
- ✅ Alle Core-Features: **Voll funktionsfähig**

---

**Erstellt am:** 2025-12-26  
**Letztes Update:** Nach Bugfix-Session
