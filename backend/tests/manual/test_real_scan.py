#!/usr/bin/env python3
"""
Real-World Test: Kompletter Scan-Flow
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from services.crawler import fetch_page_smart
from services.persistence import extract_text_from_html_v2


async def test_real_world_scan():
    """
    Real-World Test mit verschiedenen URLs
    """
    print("\n" + "="*80)
    print("🌐 REAL-WORLD TEST: Verschiedene URLs scannen")
    print("="*80)

    test_urls = [
        "https://example.com",
        "https://www.wikipedia.org",
    ]

    results = []

    for url in test_urls:
        print(f"\n📡 Teste: {url}")
        print("-" * 80)

        try:
            result = await fetch_page_smart(url, force_playwright=False)

            print(f"✅ Erfolgreich!")
            print(f"   Via: {result['via']}")
            print(f"   Duration: {result['duration']:.2f}s")
            print(f"   HTML: {len(result['html'])} chars")
            print(f"   Text: {result['content_length']} chars")

            # Validierung
            validation = {
                'url': url,
                'success': True,
                'via': result['via'],
                'html_length': len(result['html']),
                'text_length': result['content_length'],
                'issues': []
            }

            # Check 1: HTML nicht leer
            if len(result['html']) < 100:
                validation['issues'].append(f"HTML zu kurz: {len(result['html'])} chars")

            # Check 2: Text extrahiert
            if result['content_length'] < 50:
                validation['issues'].append(f"Text zu kurz: {result['content_length']} chars")

            # Check 3: Via korrekt
            if result['via'] not in ['httpx', 'playwright', 'playwright-fallback', 'playwright-error-fallback']:
                validation['issues'].append(f"Unbekannter Via-Wert: {result['via']}")

            results.append(validation)

        except Exception as e:
            print(f"❌ Fehler: {e}")
            results.append({
                'url': url,
                'success': False,
                'error': str(e),
                'issues': [str(e)]
            })

    # Zusammenfassung
    print("\n" + "="*80)
    print("📊 REAL-WORLD TEST ZUSAMMENFASSUNG")
    print("="*80)

    success_count = sum(1 for r in results if r['success'])
    total_count = len(results)

    for result in results:
        status = "✅" if result['success'] and not result.get('issues') else "⚠️" if result['success'] else "❌"
        print(f"\n{status} {result['url']}")

        if result['success']:
            print(f"   Via: {result['via']}")
            print(f"   HTML: {result['html_length']} chars")
            print(f"   Text: {result['text_length']} chars")

            if result['issues']:
                print(f"   ⚠️  Issues:")
                for issue in result['issues']:
                    print(f"      - {issue}")
        else:
            print(f"   ❌ Error: {result.get('error', 'Unknown')}")

    print(f"\n📈 Erfolgsrate: {success_count}/{total_count}")

    if success_count == total_count:
        print("\n🎉 ALLE REAL-WORLD TESTS ERFOLGREICH!")
        return 0
    else:
        print(f"\n⚠️  {total_count - success_count} Test(s) fehlgeschlagen")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_real_world_scan())
    sys.exit(exit_code)
