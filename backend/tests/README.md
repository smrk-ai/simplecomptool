# Test-Dokumentation - Simple CompTool

## 📁 Ordnerstruktur

```
backend/tests/
├── unit/          # Unit Tests (isolierte Funktions-/Klassen-Tests)
├── integration/   # Integration Tests (Multi-Komponenten-Tests, API-Tests)
├── smoke/         # Smoke Tests (Basis-Funktionalitäts-Checks)
└── manual/        # Manuelle Test-Scripts (Debugging, explorative Tests)
```

---

## 📋 Test-Kategorien

### **unit/** - Unit Tests
**Zweck**: Isolierte Tests einzelner Funktionen oder Klassen ohne externe Abhängigkeiten.

**Beispiele**:
- URL-Normalisierung (`canonicalize_url`)
- Hash-Berechnungen
- Text-Extraktion
- Validation-Funktionen

**Eigenschaften**:
- ✅ Schnell (< 100ms pro Test)
- ✅ Keine Netzwerk-Calls
- ✅ Keine Browser-Instanzen
- ✅ Keine Datenbank-Zugriffe

**Ausführen**:
```bash
pytest backend/tests/unit/ -v
```

---

### **integration/** - Integration Tests
**Zweck**: Tests für Interaktionen zwischen mehreren Komponenten (API-Endpoints, Crawler + DB, etc.).

**Beispiele**:
- `/api/scan` Endpoint (POST Request → Crawler → DB → Response)
- Crawler + Persistence Integration
- Browser Manager + Crawler Integration

**Eigenschaften**:
- ⏱️ Langsamer (1-10s pro Test)
- 🌐 Kann echte HTTP-Requests machen
- 🗄️ Kann Test-Datenbank verwenden
- 🎭 Kann Browser-Instanz starten

**Ausführen**:
```bash
pytest backend/tests/integration/ -v
```

---

### **smoke/** - Smoke Tests
**Zweck**: Schnelle Basis-Checks für kritische Funktionen (Deployment-Validierung).

**Beispiele**:
- API Server startet
- Datenbank-Verbindung funktioniert
- Browser kann gestartet werden
- Environment-Variablen sind gesetzt

**Eigenschaften**:
- ⚡ Ultra-schnell (< 5s gesamt)
- 🎯 Kritische Pfade only
- 🚀 Deployment-Gates

**Ausführen**:
```bash
pytest backend/tests/smoke/ -v
```

---

### **manual/** - Manuelle Test-Scripts
**Zweck**: Scripts für manuelle Tests, Debugging, und explorative Tests.

**Beispiele**:
- `test_bug_fixes.py` - Manuelle Verifikation von Bug-Fixes
- `test_real_scan.py` - Manueller Test mit echten URLs
- `check_and_test.py` - Diagnostics & System-Checks

**Eigenschaften**:
- 🛠️ Nicht automatisiert
- 🔍 Explorative Tests
- 🐛 Debugging-Hilfen
- 📊 Performance-Messungen

**Ausführen**:
```bash
# Einzeln ausführen
python backend/tests/manual/test_real_scan.py
python backend/tests/manual/check_and_test.py
```

---

## 🚀 Alle Tests ausführen

### Alle automatisierten Tests (unit + integration + smoke)
```bash
pytest backend/tests/ -v --ignore=backend/tests/manual/
```

### Nur schnelle Tests (unit + smoke)
```bash
pytest backend/tests/unit/ backend/tests/smoke/ -v
```

### Mit Coverage-Report
```bash
pytest backend/tests/ --cov=backend --cov-report=html --ignore=backend/tests/manual/
```

---

## 📝 Test-Naming-Conventions

### Dateinamen
- `test_*.py` - Prefix für pytest-Discovery
- `test_url_utils.py` - Unit Tests für url_utils.py
- `test_api_scan.py` - Integration Test für /api/scan

### Funktionsnamen
- `test_<function>_<scenario>` - z.B. `test_canonicalize_url_strips_www`
- `test_<endpoint>_<status>` - z.B. `test_scan_api_success`

### Beispiel
```python
# backend/tests/unit/test_url_utils.py
def test_canonicalize_url_strips_www():
    result = canonicalize_url("https://www.example.com/page")
    assert result == "https://example.com/page"

def test_canonicalize_url_enforces_https():
    result = canonicalize_url("http://example.com")
    assert result.startswith("https://")
```

---

## 🎯 Test-Coverage-Ziele

| Kategorie | Aktuell | Ziel |
|-----------|---------|------|
| **Unit Tests** | 0% | 80% |
| **Integration Tests** | 0% | 50% |
| **Smoke Tests** | 0% | 100% |

---

## 📚 Best Practices

### ✅ DO
- Tests isoliert halten (keine gegenseitigen Abhängigkeiten)
- Fixtures für Setup/Teardown verwenden
- Klare, beschreibende Test-Namen
- Einen Assertion-Punkt pro Test (wenn möglich)
- Test-Daten in `fixtures/` ablegen

### ❌ DON'T
- Produktions-Datenbank in Tests verwenden
- Tests mit `time.sleep()` verlangsamen
- Hardcoded Secrets in Tests
- Externe APIs ohne Mocking testen
- Tests überspringen ohne Kommentar

---

## 🔧 Pytest-Konfiguration

### pytest.ini (falls noch nicht vorhanden)
```ini
[pytest]
testpaths = backend/tests
python_files = test_*.py
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: integration tests
    smoke: smoke tests
```

---

## 📦 Dependencies

```bash
# Test-Dependencies installieren
pip install pytest pytest-asyncio pytest-cov
```

---

## 🐛 Debugging

### Einzelnen Test debuggen
```bash
pytest backend/tests/unit/test_url_utils.py::test_canonicalize_url_strips_www -v -s
```

### Mit Debugger (pdb)
```python
def test_my_function():
    import pdb; pdb.set_trace()  # Breakpoint
    result = my_function()
    assert result == expected
```

---

## 📈 Nächste Schritte

1. **Unit Tests schreiben** für:
   - `backend/utils/url_utils.py`
   - `backend/services/persistence.py` (validation functions)
   - `backend/services/text_extraction.py`

2. **Integration Tests schreiben** für:
   - `/api/scan` Endpoint
   - Crawler + Browser Manager
   - Full Scan Workflow

3. **Smoke Tests schreiben** für:
   - API Server Health
   - Database Connection
   - Browser Launch

4. **Coverage erhöhen** auf mindestens 50%

---

**Letzte Aktualisierung**: 2025-12-27
**Version**: v.03.1.1
