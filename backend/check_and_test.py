#!/usr/bin/env python3
"""
Prüft Supabase-Setup und führt Tests durch
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Environment Variables laden
env_path = Path(__file__).parent.parent / '.env.local'
load_dotenv(dotenv_path=env_path)

sys.path.insert(0, str(Path(__file__).parent))

from services.persistence import init_db, supabase

def check_tables():
    """Prüft ob alle Tabellen existieren"""
    print("🔍 Prüfe Supabase-Tabellen...")
    
    init_db()
    
    tables = ['competitors', 'snapshots', 'pages', 'socials', 'profiles']
    all_exist = True
    
    for table in tables:
        try:
            result = supabase.table(table).select('*').limit(0).execute()
            print(f"   ✅ Tabelle '{table}' existiert")
        except Exception as e:
            error_str = str(e)
            if 'does not exist' in error_str.lower() or 'PGRST205' in error_str:
                print(f"   ❌ Tabelle '{table}' existiert nicht")
                all_exist = False
            else:
                print(f"   ⚠️  Tabelle '{table}': {error_str[:80]}")
    
    return all_exist

def wait_for_tables(max_wait=60):
    """Wartet bis alle Tabellen existieren"""
    print(f"\n⏳ Warte auf Tabellen-Erstellung (max {max_wait}s)...")
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if check_tables():
            print("\n✅ Alle Tabellen existieren!")
            return True
        
        print("   Warte 5 Sekunden...")
        time.sleep(5)
    
    print("\n❌ Timeout: Tabellen wurden nicht erstellt")
    return False

if __name__ == "__main__":
    print("🚀 Supabase Setup Check & Test")
    print("=" * 50)
    
    if check_tables():
        print("\n✅ Setup vollständig - Bereit für Tests!")
        sys.exit(0)
    else:
        print("\n⚠️  Tabellen fehlen noch.")
        print("📝 Bitte führen Sie das SQL-Script im Supabase Dashboard aus:")
        print("   1. Öffnen Sie: https://supabase.com/dashboard/project/xvxwvmyrzpjzvyclftrw/sql/new")
        print("   2. Kopieren Sie den Inhalt von supabase_schema.sql")
        print("   3. Führen Sie das Script aus")
        print("\n⏳ Warte auf Tabellen-Erstellung...")
        
        if wait_for_tables():
            print("\n✅ Setup erfolgreich!")
            sys.exit(0)
        else:
            print("\n❌ Setup nicht vollständig")
            sys.exit(1)

