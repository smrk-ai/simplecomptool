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
