# Environment Variables

Dieses Dokument beschreibt alle Environment-Variablen für Simple CompTool.

## Erforderliche Variablen

### Supabase
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SERVICE_ROLE_KEY=your-service-role-key
```

### OpenAI (Optional)
```bash
OPENAI_API_KEY=your-openai-api-key
```

## Konfigurierbare Variablen

### Backend
```bash
# CORS Origins (komma-separiert, Standard: http://localhost:3000)
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Globaler Scan-Timeout in Sekunden (Standard: 60.0)
GLOBAL_SCAN_TIMEOUT=60.0
```

### Frontend
```bash
# API Base URL für Backend-Kommunikation (Standard: http://localhost:8000)
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Setup

1. Kopiere `.env.example` nach `.env.local`
2. Fülle die erforderlichen Werte aus
3. Passe die konfigurierbaren Werte nach Bedarf an

## Standardwerte

Alle konfigurierbaren Variablen haben sinnvolle Standardwerte für die lokale Entwicklung.

## Bekannte Probleme

### EPERM-Fehler beim Frontend-Start

**Symptom:**
```
Error: EPERM: operation not permitted, open '.../node_modules/next/dist/...'
```

**Ursache:**
Sandbox-Berechtigungsproblem mit `node_modules`. Dies ist kein Code-Problem, sondern ein System-Berechtigungsproblem.

**Lösung:**
1. Frontend außerhalb des Sandbox-Modus starten
2. `node_modules` Berechtigungen prüfen: `ls -la frontend/node_modules`
3. Falls nötig: `chmod -R u+r frontend/node_modules`
4. Oder: `node_modules` neu installieren: `cd frontend && rm -rf node_modules && npm install`
