-- Supabase Schema für Simple CompTool
-- Führen Sie dieses Script in der Supabase SQL-Editor aus

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
    raw_path TEXT,  -- Pfad in Supabase Storage
    text_path TEXT, -- Pfad in Supabase Storage
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
CREATE POLICY "Allow all operations for anon" ON competitors FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations for anon" ON snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations for anon" ON pages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations for anon" ON socials FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all operations for anon" ON profiles FOR ALL USING (true) WITH CHECK (true);

-- Storage Buckets erstellen (werden automatisch über Python-API erstellt, aber zur Dokumentation hier)
-- Diese werden über die Supabase Dashboard oder API erstellt:
-- Bucket: html-files (private)
-- Bucket: txt-files (private)
