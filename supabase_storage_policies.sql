-- Supabase Storage Policies für Simple CompTool
-- Führen Sie dieses Script in der Supabase SQL-Editor aus
-- NACH dem Erstellen der Buckets

-- Storage Policies für html-files Bucket
-- Erlaube Uploads für anon
CREATE POLICY "Allow anon uploads to html-files"
ON storage.objects FOR INSERT
TO anon
WITH CHECK (bucket_id = 'html-files');

-- Erlaube Downloads für anon
CREATE POLICY "Allow anon downloads from html-files"
ON storage.objects FOR SELECT
TO anon
USING (bucket_id = 'html-files');

-- Erlaube Updates für anon
CREATE POLICY "Allow anon updates to html-files"
ON storage.objects FOR UPDATE
TO anon
USING (bucket_id = 'html-files');

-- Erlaube Deletes für anon
CREATE POLICY "Allow anon deletes from html-files"
ON storage.objects FOR DELETE
TO anon
USING (bucket_id = 'html-files');

-- Storage Policies für txt-files Bucket
-- Erlaube Uploads für anon
CREATE POLICY "Allow anon uploads to txt-files"
ON storage.objects FOR INSERT
TO anon
WITH CHECK (bucket_id = 'txt-files');

-- Erlaube Downloads für anon
CREATE POLICY "Allow anon downloads from txt-files"
ON storage.objects FOR SELECT
TO anon
USING (bucket_id = 'txt-files');

-- Erlaube Updates für anon
CREATE POLICY "Allow anon updates to txt-files"
ON storage.objects FOR UPDATE
TO anon
USING (bucket_id = 'txt-files');

-- Erlaube Deletes für anon
CREATE POLICY "Allow anon deletes from txt-files"
ON storage.objects FOR DELETE
TO anon
USING (bucket_id = 'txt-files');

