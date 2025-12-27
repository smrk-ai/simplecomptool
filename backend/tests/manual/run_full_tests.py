#!/usr/bin/env python3
"""
Vollständiger Test des Scan-Workflows mit Supabase
"""

import os
import sys
import time
import json
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env.local'
load_dotenv(dotenv_path=env_path)

sys.path.insert(0, str(Path(__file__).parent))

from services import persistence

def check_storage_policies():
    """Prüft ob Storage Policies aktiv sind"""
    persistence.init_db()
    supabase = persistence.supabase
    
    if not supabase:
        return False
    
    test_html = '<html><body>Test</body></html>'
    try:
        result = supabase.storage.from_('html-files').upload(
            path='test/test.html',
            file=test_html.encode('utf-8'),
            file_options={'content-type': 'text/html'}
        )
        supabase.storage.from_('html-files').remove(['test/test.html'])
        return True
    except Exception as e:
        error_str = str(e)
        if 'row-level security' in error_str.lower() or 'unauthorized' in error_str.lower():
            return False
        return False

def test_scan():
    """Testet Scan-Endpoint"""
    import httpx
    
    print("\n📡 Teste Scan-Endpoint...")
    
    try:
        response = httpx.post(
            "http://localhost:8000/api/scan",
            json={"url": "https://example.com", "llm": False},
            timeout=60.0
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Scan erfolgreich")
            print(f"   Competitor ID: {data.get('competitor_id')}")
            print(f"   Snapshot ID: {data.get('snapshot_id')}")
            print(f"   Pages: {len(data.get('pages', []))}")
            return data
        else:
            print(f"❌ Scan fehlgeschlagen: {response.status_code}")
            print(f"   {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Fehler beim Scan: {e}")
        return None

def test_snapshot_details(snapshot_id):
    """Testet Snapshot-Details Endpoint"""
    import httpx
    
    print(f"\n📋 Teste Snapshot-Details für {snapshot_id}...")
    
    try:
        response = httpx.get(
            f"http://localhost:8000/api/snapshots/{snapshot_id}",
            timeout=10.0
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Snapshot-Details erfolgreich")
            print(f"   Pages: {len(data.get('pages', []))}")
            return data
        else:
            print(f"❌ Snapshot-Details fehlgeschlagen: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Snapshot-Details: {e}")
        return None

def test_download_endpoints(snapshot_data):
    """Testet Download-Endpoints"""
    import httpx
    
    print("\n📥 Teste Download-Endpoints...")
    
    pages = snapshot_data.get('pages', [])
    if not pages:
        print("⚠️  Keine Pages zum Testen")
        return
    
    page = pages[0]
    page_id = page.get('id')
    
    if not page_id:
        print("⚠️  Page hat keine ID")
        return
    
    # Test Raw Download
    try:
        response = httpx.get(
            f"http://localhost:8000/api/pages/{page_id}/raw",
            timeout=10.0
        )
        
        if response.status_code == 200:
            print(f"✅ Raw Download erfolgreich ({len(response.content)} bytes)")
        else:
            print(f"❌ Raw Download fehlgeschlagen: {response.status_code}")
    except Exception as e:
        print(f"❌ Fehler beim Raw Download: {e}")
    
    # Test Text Download
    try:
        response = httpx.get(
            f"http://localhost:8000/api/pages/{page_id}/text",
            timeout=10.0
        )
        
        if response.status_code == 200:
            print(f"✅ Text Download erfolgreich ({len(response.content)} bytes)")
        else:
            print(f"❌ Text Download fehlgeschlagen: {response.status_code}")
    except Exception as e:
        print(f"❌ Fehler beim Text Download: {e}")

if __name__ == "__main__":
    print("🚀 Vollständiger Test des Scan-Workflows")
    print("=" * 50)
    
    # 1. Prüfe Storage Policies
    print("\n1️⃣ Prüfe Storage Policies...")
    if not check_storage_policies():
        print("❌ Storage Policies fehlen noch")
        print("Bitte führen Sie supabase_storage_policies.sql im Supabase Dashboard aus")
        print("\n⏳ Warte auf Storage Policies (max 60 Sekunden)...")
        
        start_time = time.time()
        while time.time() - start_time < 60:
            if check_storage_policies():
                print("✅ Storage Policies sind jetzt aktiv!")
                break
            time.sleep(5)
        else:
            print("❌ Timeout: Storage Policies wurden nicht angewendet")
            sys.exit(1)
    else:
        print("✅ Storage Policies sind aktiv")
    
    # 2. Teste Scan
    scan_result = test_scan()
    if not scan_result:
        print("\n❌ Scan-Test fehlgeschlagen")
        sys.exit(1)
    
    snapshot_id = scan_result.get('snapshot_id')
    if not snapshot_id:
        print("\n❌ Keine Snapshot-ID erhalten")
        sys.exit(1)
    
    # 3. Teste Snapshot-Details
    snapshot_data = test_snapshot_details(snapshot_id)
    if not snapshot_data:
        print("\n❌ Snapshot-Details-Test fehlgeschlagen")
        sys.exit(1)
    
    # 4. Teste Download-Endpoints
    test_download_endpoints(snapshot_data)
    
    print("\n" + "=" * 50)
    print("✅ Alle Tests erfolgreich abgeschlossen!")

