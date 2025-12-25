#!/usr/bin/env python3
"""
Wartet auf Storage Policies und testet dann Uploads
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env.local'
load_dotenv(dotenv_path=env_path)

sys.path.insert(0, str(Path(__file__).parent))

from services import persistence

def test_storage_upload():
    """Testet Storage-Upload"""
    persistence.init_db()
    supabase = persistence.supabase
    
    if not supabase:
        return False
    
    test_html = '<html><body>Test</body></html>'
    test_path = 'test/test.html'

    try:
        result = supabase.storage.from_('html-files').upload(
            path=test_path,
            file=test_html.encode('utf-8'),
            file_options={'content-type': 'text/html'}
        )
        
        # Lösche Test-Datei
        supabase.storage.from_('html-files').remove([test_path])
        return True
        
    except Exception as e:
        error_str = str(e)
        if 'row-level security' in error_str.lower() or 'unauthorized' in error_str.lower():
            return False
        else:
            print(f"Unerwarteter Fehler: {e}")
            return False

if __name__ == "__main__":
    print("🔍 Prüfe Storage Policies...")
    
    persistence.init_db()
    
    max_wait = 30  # 30 Sekunden für schnellen Test
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        if test_storage_upload():
            print("✅ Storage Policies sind aktiv!")
            sys.exit(0)
        
        print("   Warte auf Storage Policies... (10 Sekunden)")
        time.sleep(10)
    
    print("❌ Timeout: Storage Policies wurden nicht angewendet")
    print("Bitte führen Sie supabase_storage_policies.sql im Supabase Dashboard aus")
    sys.exit(1)

