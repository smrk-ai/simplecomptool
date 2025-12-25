# Simple CompTool v3

Ein einfaches Competitor-Monitoring Tool als Monorepo mit Python Backend und Next.js Frontend.

## Architektur

- **Backend**: Python 3.12 + FastAPI + SQLite + Playwright
- **Frontend**: Next.js 15 + TypeScript + CSS Modules
- **Datenbank**: SQLite (lokal)
- **Browser Automation**: Playwright (headless Chromium)

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

# Optional: .env Datei für OpenAI API Key erstellen
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

## Datenstruktur

### Lokale Speicherung
- **Datenbank**: `backend/data/app.db`
- **Snapshots**: `backend/data/snapshots/`
- **Logs**: `backend/data/logs/`

### Datenbank-Schema
- **competitors**: id, name, url, created_at
- **snapshots**: id, competitor_id, url, content, created_at

## Funktionen

- ✅ Website-Scanning mit Playwright
- ✅ Lokale SQLite-Datenspeicherung
- ✅ RESTful API mit FastAPI
- ✅ CORS-Unterstützung für Frontend
- ✅ Responsive Web-Interface
- ✅ TypeScript-Unterstützung

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
1. Backend: Uvicorn mit mehreren Workern starten
2. Frontend: `npm run build && npm start`
3. Reverse Proxy (nginx) für beide Services konfigurieren
4. Environment-Variablen für OpenAI API Key setzen

## Lizenz

Dieses Projekt ist für lokale Entwicklung und Tests gedacht.
