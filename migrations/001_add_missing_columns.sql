-- Migration 001: Add missing columns to pages table
-- Date: 2025-12-27
-- Purpose: Fix schema mismatch between code and database

-- Add missing columns for change detection and metrics
ALTER TABLE pages ADD COLUMN IF NOT EXISTS canonical_url TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS changed BOOLEAN DEFAULT TRUE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS prev_page_id UUID;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS text_length INTEGER;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS normalized_len INTEGER;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS has_truncation BOOLEAN DEFAULT FALSE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS extraction_version TEXT DEFAULT 'v1';
ALTER TABLE pages ADD COLUMN IF NOT EXISTS fetch_duration FLOAT;

-- Add performance indexes
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(snapshot_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_pages_changed ON pages(snapshot_id, changed);
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_created ON snapshots(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_sha256 ON pages(sha256_text);
CREATE INDEX IF NOT EXISTS idx_profiles_snapshot ON profiles(snapshot_id);

-- Verify columns exist
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'pages'
ORDER BY ordinal_position;
