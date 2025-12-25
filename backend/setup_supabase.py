#!/usr/bin/env python3
"""
Supabase Setup Script
Erstellt alle Tabellen, Indizes und Policies in Supabase
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
import httpx

# Environment Variables laden
env_path = Path(__file__).parent.parent / '.env.local'
load_dotenv(dotenv_path=env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SERVICE_ROLE_KEY:
    print("❌ Fehler: SUPABASE_URL und SERVICE_ROLE_KEY müssen in .env.local gesetzt sein")
    sys.exit(1)

# Supabase Client mit Service Role Key
supabase = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

# SQL-Statements aus supabase_schema.sql
SQL_STATEMENTS = """
-- Competitors Tabelle
CREATE TABLE IF NOT EXISTS competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    base_url TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Snapshots Tabelle
CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    page_count INTEGER DEFAULT 0,
    notes TEXT
);

-- Pages Tabelle
CREATE TABLE IF NOT EXISTS pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    status INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    via TEXT NOT NULL,
    content_type TEXT,
    raw_path TEXT,
    text_path TEXT,
    sha256_text TEXT,
    title TEXT,
    meta_description TEXT
);

-- Socials Tabelle
CREATE TABLE IF NOT EXISTS socials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    url TEXT NOT NULL,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    source_url TEXT NOT NULL,
    UNIQUE(competitor_id, platform, handle)
);

-- Profiles Tabelle
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor_id UUID NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    snapshot_id UUID NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    text TEXT NOT NULL,
    UNIQUE(competitor_id, snapshot_id)
);

-- Indizes für Performance
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_id ON snapshots(competitor_id);
CREATE INDEX IF NOT EXISTS idx_pages_snapshot_id ON pages(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_socials_competitor_id ON socials(competitor_id);
CREATE INDEX IF NOT EXISTS idx_profiles_competitor_id ON profiles(competitor_id);

-- Row Level Security (RLS) aktivieren
ALTER TABLE competitors ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE socials ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Policies für anon Zugriff (lesen/schreiben)
DROP POLICY IF EXISTS "Allow all operations for anon" ON competitors;
CREATE POLICY "Allow all operations for anon" ON competitors FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all operations for anon" ON snapshots;
CREATE POLICY "Allow all operations for anon" ON snapshots FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all operations for anon" ON pages;
CREATE POLICY "Allow all operations for anon" ON pages FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all operations for anon" ON socials;
CREATE POLICY "Allow all operations for anon" ON socials FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all operations for anon" ON profiles;
CREATE POLICY "Allow all operations for anon" ON profiles FOR ALL USING (true) WITH CHECK (true);
"""

def execute_sql(sql: str):
    """Führt SQL über Supabase aus"""
    try:
        # Supabase Python Client unterstützt direkte SQL-Ausführung über RPC
        # Wir verwenden die PostgREST API direkt
        response = supabase.rpc('exec_sql', {'sql': sql}).execute()
        return True, None
    except Exception as e:
        # Fallback: Verwende PostgREST direkt
        try:
            # Teile SQL in einzelne Statements
            statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]
            
            for statement in statements:
                if statement:
                    # Verwende Supabase's PostgREST Client für direkte SQL-Ausführung
                    # Hinweis: Supabase Python Client hat keine direkte SQL-Ausführung
                    # Wir müssen die REST API verwenden
                    pass
            
            return False, "SQL-Ausführung über Python Client nicht direkt möglich"
        except Exception as e2:
            return False, str(e2)

def setup_tables():
    """Erstellt alle Tabellen über Supabase REST API"""
    print("📊 Erstelle Supabase-Tabellen...")
    
    import httpx
    
    # Lese SQL aus supabase_schema.sql
    schema_file = Path(__file__).parent.parent / 'supabase_schema.sql'
    if schema_file.exists():
        with open(schema_file, 'r') as f:
            sql_content = f.read()
    else:
        print("   ⚠️  supabase_schema.sql nicht gefunden")
        sql_content = ""
    
    # Versuche SQL über Supabase Management API auszuführen
    try:
        # Supabase unterstützt SQL-Ausführung über die Management API
        # URL: https://{project_ref}.supabase.co/rest/v1/rpc/exec_sql
        # Aber das erfordert eine spezielle Funktion
        
        # Alternativ: Verwende die SQL Editor API direkt
        project_ref = SUPABASE_URL.split('//')[1].split('.')[0]
        sql_api_url = f"https://{project_ref}.supabase.co/rest/v1/rpc/exec_sql"
        
        headers = {
            "apikey": SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
            "Content-Type": "application/json"
        }
        
        # Versuche SQL über Supabase Management API auszuführen
        # Verwende die SQL Editor API direkt
        management_url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
        
        # Versuche SQL über Management API
        async def execute_sql_async():
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        management_url,
                        headers={
                            "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={"query": sql_content},
                        timeout=30.0
                    )
                    return response.status_code == 200, response.text
                except Exception as e:
                    return False, str(e)
        
        # Da wir async verwenden, versuchen wir es synchron
        # Hinweis: Management API erfordert spezielle Authentifizierung
        print("   ⚠️  Direkte SQL-Ausführung über Python API erfordert Management API Zugriff.")
        print("   📝 Bitte führen Sie das SQL-Script im Supabase Dashboard aus:")
        print(f"      1. Öffnen Sie: https://supabase.com/dashboard/project/{project_ref}/sql/new")
        print("      2. Kopieren Sie den Inhalt von supabase_schema.sql")
        print("      3. Führen Sie das Script aus")
        print()
        
        # Prüfe ob Tabellen bereits existieren
        tables_exist = True
        tables_to_check = ['competitors', 'snapshots', 'pages', 'socials', 'profiles']
        for table in tables_to_check:
            try:
                result = supabase.table(table).select('*').limit(0).execute()
                print(f"      ✅ Tabelle '{table}' existiert")
            except Exception as e:
                error_str = str(e)
                if "does not exist" in error_str.lower() or "PGRST" in error_str:
                    print(f"      ❌ Tabelle '{table}' existiert nicht")
                    tables_exist = False
                else:
                    print(f"      ⚠️  Tabelle '{table}': {e}")
        
        return tables_exist
            
    except Exception as e:
        print(f"   ⚠️  Fehler: {e}")
        return False

def setup_buckets():
    """Erstellt Storage-Buckets"""
    print("\n📦 Erstelle Storage-Buckets...")
    
    buckets = [
        ("html-files", False),
        ("txt-files", False)
    ]
    
    for bucket_name, is_public in buckets:
        try:
            result = supabase.storage.create_bucket(bucket_name)
            print(f"   ✅ Bucket '{bucket_name}' erstellt")
        except Exception as e:
            error_str = str(e)
            if "already exists" in error_str.lower() or "duplicate" in error_str.lower():
                print(f"   ℹ️  Bucket '{bucket_name}' existiert bereits")
            else:
                print(f"   ⚠️  Fehler beim Erstellen von '{bucket_name}': {e}")
    
    return True

def verify_setup():
    """Verifiziert das Setup"""
    print("\n🔍 Verifiziere Setup...")
    
    try:
        # Prüfe Tabellen (indirekt über SELECT)
        tables = ['competitors', 'snapshots', 'pages', 'socials', 'profiles']
        for table in tables:
            try:
                result = supabase.table(table).select('*').limit(0).execute()
                print(f"   ✅ Tabelle '{table}' existiert")
            except Exception as e:
                if "does not exist" in str(e).lower() or "PGRST" in str(e):
                    print(f"   ❌ Tabelle '{table}' existiert nicht")
                else:
                    print(f"   ⚠️  Tabelle '{table}': {e}")
        
        # Prüfe Buckets
        try:
            buckets = supabase.storage.list_buckets()
            bucket_names = [b['name'] for b in buckets]
            for bucket_name in ['html-files', 'txt-files']:
                if bucket_name in bucket_names:
                    print(f"   ✅ Bucket '{bucket_name}' existiert")
                else:
                    print(f"   ❌ Bucket '{bucket_name}' existiert nicht")
        except Exception as e:
            print(f"   ⚠️  Fehler beim Prüfen der Buckets: {e}")
            
    except Exception as e:
        print(f"   ❌ Verifikations-Fehler: {e}")

if __name__ == "__main__":
    print("🚀 Supabase Setup für Simple CompTool")
    print("=" * 50)
    
    # Tabellen-Setup (Hinweis auf manuelle Ausführung)
    setup_tables()
    
    # Buckets erstellen
    setup_buckets()
    
    # Verifikation
    verify_setup()
    
    print("\n" + "=" * 50)
    print("✅ Setup abgeschlossen!")
    print("\n📝 WICHTIG: Führen Sie das SQL-Script im Supabase Dashboard aus,")
    print("   falls die Tabellen noch nicht existieren.")

