#!/usr/bin/env python3
import asyncio
import sys
import os

# Füge Backend zum Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from main import scan_endpoint, ScanRequest

async def test_scan_endpoint():
    """Teste den scan_endpoint direkt"""
    print("🧪 Teste scan_endpoint direkt...")

    try:
        # Erstelle Request
        request = ScanRequest(
            url="https://example.com",
            name="Test Company",
            llm=False
        )

        print(f"📡 Request: {request.url}, llm={request.llm}")

        # Rufe Endpoint auf
        result = await scan_endpoint(request)

        print("✅ Scan erfolgreich!")
        print(f"📊 Competitor ID: {result.competitor_id}")
        print(f"📊 Snapshot ID: {result.snapshot_id}")
        print(f"📄 Pages: {len(result.pages)}")
        print(f"🤖 Profile: {result.profile or 'None'}")
        print(f"⚠️  Error: {result.error or 'None'}")

        return True

    except Exception as e:
        print(f"❌ Fehler: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_scan_endpoint())
    print(f"\n{'✅ Test erfolgreich!' if success else '❌ Test fehlgeschlagen!'}")
