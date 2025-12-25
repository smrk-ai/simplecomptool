-- SUPABASE MIGRATION: Async Status + Design Rules + Hash-Gate Support
-- Execute this entire block in Supabase SQL Editor
-- Note: Some ALTER TABLE ADD COLUMN statements may fail if columns already exist

-- =============================================================================
-- 1) SNAPSHOTS TABLE EXTENSIONS
-- =============================================================================

-- Add async status and progress fields
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS status text DEFAULT 'queued' NOT NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS progress_pages_done int DEFAULT 0 NOT NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS progress_pages_total int DEFAULT 0 NOT NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS started_at timestamptz DEFAULT now();
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS finished_at timestamptz NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS error_code text NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS error_message text NULL;

-- Add versioning fields for design rules
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS extraction_version text DEFAULT 'v1' NOT NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS page_set_version text DEFAULT 'v1' NOT NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS page_set_hash text NULL;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS page_set_changed boolean DEFAULT FALSE;
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS page_set_json jsonb NULL;

-- =============================================================================
-- 2) PAGES TABLE EXTENSIONS (Hash-Gate/Rescan Support)
-- =============================================================================

-- Add change detection fields
ALTER TABLE pages ADD COLUMN IF NOT EXISTS canonical_url text NOT NULL DEFAULT '';
ALTER TABLE pages ADD COLUMN IF NOT EXISTS changed boolean DEFAULT true NOT NULL;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS prev_page_id uuid NULL;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS normalized_len int NULL;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS extraction_version text DEFAULT 'v1' NOT NULL;

-- =============================================================================
-- 3) INDEXES
-- =============================================================================

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_snapshots_competitor_created_desc ON snapshots(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_snapshot_canonical ON pages(snapshot_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(canonical_url);

-- =============================================================================
-- 4) CONSTRAINTS (Safe - won't break existing data)
-- =============================================================================

-- Only add NOT NULL constraints if columns are populated or have defaults
-- Note: These may fail if existing data violates constraints - remove if needed
-- ALTER TABLE pages ADD CONSTRAINT IF NOT EXISTS pages_canonical_url_not_null CHECK (canonical_url IS NOT NULL);
-- ALTER TABLE pages ADD CONSTRAINT IF NOT EXISTS pages_changed_not_null CHECK (changed IS NOT NULL);

-- Optional: Add foreign key constraint for prev_page_id (only if pages.id is uuid)
-- ALTER TABLE pages ADD CONSTRAINT IF NOT EXISTS fk_pages_prev_page_id FOREIGN KEY (prev_page_id) REFERENCES pages(id);

-- =============================================================================
-- 5) BACKFILL EXISTING DATA (Safe operations)
-- =============================================================================

-- Backfill snapshots status and progress for existing rows
UPDATE snapshots
SET
  status = 'done',
  progress_pages_done = COALESCE(progress_pages_total, page_count),
  progress_pages_total = COALESCE(progress_pages_total, page_count),
  started_at = COALESCE(started_at, created_at),
  finished_at = COALESCE(finished_at, created_at),
  extraction_version = COALESCE(extraction_version, 'v1'),
  page_set_version = COALESCE(page_set_version, 'v1')
WHERE status IS NULL OR progress_pages_total = 0;

-- Backfill canonical_url from url with basic normalization
UPDATE pages
SET canonical_url = regexp_replace(
  regexp_replace(url, '#.*$', ''),  -- remove fragment
  '[?&](utm_[^&]*|fbclid|gclid|gclsrc|_ga)[^&]*', '', 'g'  -- remove tracking params
)
WHERE canonical_url = '' OR canonical_url IS NULL;

-- Backfill changed = true for existing pages (assume all are "new" initially)
UPDATE pages SET changed = true WHERE changed IS NULL;

-- Backfill extraction_version
UPDATE pages SET extraction_version = 'v1' WHERE extraction_version IS NULL;

-- =============================================================================
-- VERIFICATION QUERIES (Optional - run after migration)
-- =============================================================================

-- Check snapshots have required fields
-- SELECT id, status, progress_pages_done, progress_pages_total, extraction_version, page_set_version FROM snapshots LIMIT 5;

-- Check pages have change detection fields
-- SELECT id, canonical_url, changed, prev_page_id, extraction_version FROM pages LIMIT 5;

-- Count total rows
-- SELECT 'snapshots' as table_name, count(*) as total_rows FROM snapshots
-- UNION ALL
-- SELECT 'pages' as table_name, count(*) as total_rows FROM pages;
