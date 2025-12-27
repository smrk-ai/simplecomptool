-- Migration 002: Performance Indexes
-- Datum: 2025-12-27
-- Zweck: Fügt fehlende Indexes für bessere Query-Performance hinzu

-- Index für SHA256 Text Hash Vergleiche (Change Detection)
-- Nutzen: Schnellere Lookups beim Vergleichen von Page-Inhalten
CREATE INDEX IF NOT EXISTS idx_pages_sha256
ON pages(sha256_text);

-- Index für Profile Lookups per Snapshot
-- Nutzen: Schnelleres Laden von Profilen für einen bestimmten Snapshot
CREATE INDEX IF NOT EXISTS idx_profiles_snapshot
ON profiles(snapshot_id);

-- Verify Indexes
-- Zeigt alle Indexes auf pages und profiles Tabellen
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('pages', 'profiles')
ORDER BY tablename, indexname;
