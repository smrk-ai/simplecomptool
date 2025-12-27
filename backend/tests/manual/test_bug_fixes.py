#!/usr/bin/env python3
"""
Test-Script für alle 4 Bug-Fixes
"""
import asyncio
import sys
import os

# Backend-Pfad hinzufügen
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from services.crawler import fetch_page_smart
from services.persistence import extract_text_from_html_v2, init_db


async def test_bug_1_and_2():
    """
    TEST BUG #1 & #2 (crawler.py):
    - httpx Response wird korrekt als String behandelt (kein tuple error)
    - extract_text_from_html_v2 wird verwendet und gibt ~1200+ chars zurück
    """
    print("\n" + "="*80)
    print("TEST 1+2: fetch_page_smart() mit httpx + v2 Text-Extraktion")
    print("="*80)

    test_url = "https://example.com"

    try:
        result = await fetch_page_smart(test_url, force_playwright=False)

        print(f"\n✅ fetch_page_smart() erfolgreich!")
        print(f"   URL: {result['url']}")
        print(f"   Via: {result['via']}")
        print(f"   Duration: {result['duration']:.2f}s")
        print(f"   Content Length: {result['content_length']} chars")
        print(f"   HTML Length: {len(result['html'])} chars")

        # Validierung
        if result['content_length'] < 100:
            print(f"\n❌ FEHLER: Content zu kurz ({result['content_length']} chars)")
            print("   → BUG #2 nicht behoben: extract_text_from_html_v2 wird nicht korrekt genutzt")
            return False

        if "'tuple' object has no attribute" in str(result):
            print("\n❌ FEHLER: Tuple-Error erkannt")
            print("   → BUG #1 nicht behoben: httpx response wird als tuple behandelt")
            return False

        print(f"\n✅ BUG #1 & #2 BEHOBEN:")
        print(f"   - Kein tuple error")
        print(f"   - Text-Länge: {result['content_length']} chars (erwartetet: >100)")
        print(f"   - Via: {result['via']}")

        return True

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        if "'tuple' object has no attribute" in str(e):
            print("   → BUG #1 NICHT BEHOBEN: httpx response tuple error")
        return False


async def test_bug_3():
    """
    TEST BUG #3 (persistence.py):
    - save_page() nutzt extract_text_from_html_v2
    - Files werden in 'snapshots' bucket hochgeladen (nicht html-files/txt-files)

    Hinweis: Dieser Test überprüft nur die Logik, kein echter Upload
    """
    print("\n" + "="*80)
    print("TEST 3: save_page() Text-Extraktion und Storage-Bucket")
    print("="*80)

    try:
        # Test: extract_text_from_html_v2 direkt
        test_html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Test Heading</h1>
                <p>This is a test paragraph with some content.</p>
                <p>Another paragraph to make it longer.</p>
            </body>
        </html>
        """

        result = extract_text_from_html_v2(test_html)

        print(f"\n✅ extract_text_from_html_v2() erfolgreich!")
        print(f"   Text Length: {result['text_length']} chars")
        print(f"   Has Truncation: {result['has_truncation']}")
        print(f"   Extraction Version: {result['extraction_version']}")
        print(f"   Text Preview: {result['text'][:100]}...")

        # Validierung
        if result['extraction_version'] != 'v2':
            print(f"\n❌ FEHLER: Falsche Version ({result['extraction_version']})")
            return False

        if result['text_length'] < 10:
            print(f"\n❌ FEHLER: Text zu kurz ({result['text_length']} chars)")
            return False

        # Code-Review: Prüfe ob save_page() den richtigen Bucket nutzt
        print("\n📝 Code-Review für save_page():")

        with open('services/persistence.py', 'r') as f:
            code = f.read()

        if "from_('snapshots')" in code:
            print("   ✅ save_page() nutzt 'snapshots' bucket")
        else:
            print("   ❌ save_page() nutzt NICHT 'snapshots' bucket")
            return False

        if "extract_text_from_html_v2" in code:
            print("   ✅ save_page() nutzt extract_text_from_html_v2()")
        else:
            print("   ❌ save_page() nutzt NICHT extract_text_from_html_v2()")
            return False

        print(f"\n✅ BUG #3 BEHOBEN:")
        print(f"   - extract_text_from_html_v2() funktioniert korrekt")
        print(f"   - save_page() nutzt 'snapshots' bucket")

        return True

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        return False


async def test_bug_4():
    """
    TEST BUG #4 (main.py):
    - Download-Endpoints haben lokalen Fallback
    - Besseres Error Handling
    """
    print("\n" + "="*80)
    print("TEST 4: Download-Endpoints mit lokalem Fallback")
    print("="*80)

    try:
        # Code-Review: Prüfe ob Download-Endpoints Fallback haben
        print("\n📝 Code-Review für Download-Endpoints:")

        with open('main.py', 'r') as f:
            code = f.read()

        # Prüfe /api/pages/{page_id}/raw
        if 'local_path = os.path.join("backend/data/snapshots"' in code:
            print("   ✅ /api/pages/{page_id}/raw hat lokalen Fallback")
        else:
            print("   ❌ /api/pages/{page_id}/raw hat KEINEN lokalen Fallback")
            return False

        # Prüfe ob beide Endpoints den Fallback haben
        fallback_count = code.count('local_path = os.path.join("backend/data/snapshots"')
        if fallback_count >= 2:
            print(f"   ✅ Beide Endpoints haben lokalen Fallback ({fallback_count} gefunden)")
        else:
            print(f"   ❌ Nur {fallback_count} Endpoint(s) mit Fallback")
            return False

        # Prüfe Error Handling
        if 'except HTTPException:' in code and 'raise HTTPException(status_code=404' in code:
            print("   ✅ Besseres Error Handling vorhanden")
        else:
            print("   ❌ Error Handling fehlt")
            return False

        print(f"\n✅ BUG #4 BEHOBEN:")
        print(f"   - Download-Endpoints haben lokalen Fallback")
        print(f"   - Error Handling verbessert")

        return True

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        return False


async def run_all_tests():
    """Führt alle Tests aus und gibt Zusammenfassung"""

    print("\n" + "="*80)
    print("🧪 BUG-FIX VALIDATION - Alle 4 Bugs testen")
    print("="*80)

    results = {}

    # Test 1+2: crawler.py
    results['BUG #1+2 (crawler.py)'] = await test_bug_1_and_2()

    # Test 3: persistence.py
    results['BUG #3 (persistence.py)'] = await test_bug_3()

    # Test 4: main.py
    results['BUG #4 (main.py)'] = await test_bug_4()

    # Zusammenfassung
    print("\n" + "="*80)
    print("📊 ZUSAMMENFASSUNG")
    print("="*80)

    for bug, status in results.items():
        status_symbol = "✅" if status else "❌"
        status_text = "BEHOBEN" if status else "NICHT BEHOBEN"
        print(f"{status_symbol} {bug}: {status_text}")

    all_passed = all(results.values())

    if all_passed:
        print("\n🎉 ALLE BUGS ERFOLGREICH BEHOBEN!")
        return 0
    else:
        print("\n⚠️  EINIGE BUGS NOCH NICHT BEHOBEN")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
