# Simple CompTool v3

Ein einfaches Competitor-Monitoring Tool als Monorepo mit Python Backend und Next.js Frontend.

## Architektur

- **Backend**: Python 3.12 + FastAPI + SQLite + Playwright
- **Frontend**: Next.js 15 + TypeScript + CSS Modules
- **Datenbank**: SQLite (lokal: `backend/data/app.db`)
- **Browser Automation**: Playwright (headless Chromium)
- **LLM Integration**: OpenAI API (optional)

## Voraussetzungen

- Python 3.12
- Node.js 18+ und npm
- Git

## Installation und Setup

### Backend Setup

```bash
cd backend

# Virtuelle Umgebung erstellen (empfohlen)
python -m venv venv
source venv/bin/activate  # Auf Windows: venv\Scripts\activate

# Dependencies installieren
pip install -r requirements.txt

# Playwright Browser installieren
playwright install chromium

# Datenbank initialisieren (SQLite wird automatisch erstellt)
python main.py  # Beende mit Ctrl+C nach dem Start

# Optional: .env Datei für OpenAI API Key erstellen (für LLM-Profile)
# OPENAI_API_KEY=your_openai_api_key_here
```

### Frontend Setup

```bash
cd frontend

# Dependencies installieren
npm install
```

## Starten der Anwendung

### Backend starten

```bash
cd backend
python main.py
```

Der Backend-Server läuft auf: http://localhost:8000

### Frontend starten

```bash
cd frontend
npm run dev
```

Der Frontend läuft auf: http://localhost:3000

## API Endpoints

### POST /api/scan
Website scannen und Competitor anlegen.

**Request Body:**
```json
{
  "name": "Beispiel GmbH",
  "url": "https://www.beispiel.de"
}
```

**Response:**
```json
{
  "competitor_id": "uuid",
  "snapshot_id": "uuid"
}
```

### GET /api/competitors
Alle gespeicherten Competitors abrufen.

### GET /api/competitors/{competitor_id}
Einzelnen Competitor mit allen Snapshots abrufen.

### GET /api/snapshots/{snapshot_id}
Einzelnen Snapshot abrufen.

**Query-Parameter:**
- `with_previews` (boolean, default: false): Wenn true, werden Text-Previews für die ersten preview_limit Seiten geladen
- `preview_limit` (integer, default: 10): Maximale Anzahl von Seiten mit Previews

**Performance-Optimierung:** Standardmäßig werden keine Text-Previews geladen, um die Ladezeiten zu verbessern.

### GET /api/pages/{page_id}/preview
Text-Preview für eine einzelne Seite (300 Zeichen).

**Response:**
```json
{
  "page_id": "uuid",
  "text_preview": "Erste 300 Zeichen des Textes...",
  "has_more": true
}
```

## Datenstruktur

### Lokale Speicherung
- **Datenbank**: `backend/data/app.db` (SQLite)
- **Snapshots**: `backend/data/snapshots/{snapshot_id}/pages/`
- **HTML-Dateien**: `{snapshot_id}/pages/{page_id}.html`
- **Text-Dateien**: `{snapshot_id}/pages/{page_id}.txt`

### Datenbank-Schema
- **competitors**: id, name, base_url, created_at
- **snapshots**: id, competitor_id, created_at, page_count, status, progress_*, ...
- **pages**: id, snapshot_id, url, status, raw_path, text_path, title, meta_description
- **socials**: id, competitor_id, platform, handle, url, discovered_at
- **profiles**: id, competitor_id, snapshot_id, text, created_at

## Funktionen

- ✅ Website-Scanning mit Playwright (JavaScript-Rendering)
- ✅ Lokale SQLite-Datenspeicherung (keine Cloud-Abhängigkeiten)
- ✅ RESTful API mit FastAPI
- ✅ CORS-Unterstützung für Frontend
- ✅ Responsive Web-Interface
- ✅ TypeScript-Unterstützung
- ✅ Social Media Link Extraktion
- ✅ LLM-basierte Unternehmensprofile (optional mit OpenAI API)
- ✅ Datei-Downloads (HTML/TXT) für gefundene Seiten

## Entwicklung

### Backend-Tests
```bash
cd backend
python -m pytest  # (wenn Tests hinzugefügt werden)
```

### Frontend-Tests
```bash
cd frontend
npm run build  # TypeScript-Kompilierung prüfen
```

## Deployment

Für Produktionsumgebung:
1. Backend: `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4`
2. Frontend: `npm run build && npm start`
3. Reverse Proxy (nginx) für beide Services konfigurieren
4. **Keine Supabase-Keys erforderlich** - alles läuft lokal
5. Optional: `OPENAI_API_KEY` für LLM-Profile setzen

### Environment-Variablen

```bash
# Erforderlich für CORS (Frontend-URL)
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Optional für LLM-Profile
OPENAI_API_KEY=your_openai_api_key_here

# Performance-Einstellungen
GLOBAL_SCAN_TIMEOUT=60.0
PHASE_A_TIMEOUT=20.0
```

## Lizenz

Dieses Projekt ist für lokale Entwicklung und Tests gedacht.
