"""
Supabase Store Implementation

Remote persistence using Supabase database and storage.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from supabase import create_client, Client
from .base import Store

logger = logging.getLogger(__name__)


class SupabaseStore(Store):
    """
    Supabase-based persistence store with remote database and storage.
    """

    def __init__(self, supabase_url: str, supabase_key: str, storage_bucket: str = "snapshots"):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.storage_bucket = storage_bucket
        self.client: Optional[Client] = None

    async def init(self) -> None:
        """Initialize Supabase client."""
        try:
            self.client = create_client(self.supabase_url, self.supabase_key)
            logger.info("Supabase client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise

    async def upsert_competitor(self, name: Optional[str], base_url: str) -> str:
        """Create or update competitor by base_url."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Check if competitor exists
            result = self.client.table('competitors').select('id').eq('base_url', base_url).execute()

            if result.data:
                competitor_id = result.data[0]['id']
                logger.debug(f"Existing competitor found: {competitor_id}")
                return competitor_id

            # Create new competitor
            competitor_data = {
                'name': name,
                'base_url': base_url,
                'created_at': datetime.now().isoformat()
            }

            result = self.client.table('competitors').insert(competitor_data).execute()
            competitor_id = result.data[0]['id']

            logger.info(f"New competitor created: {competitor_id}")
            return competitor_id

        except Exception as e:
            logger.error(f"Error in upsert_competitor: {e}")
            raise

    async def create_snapshot(self, competitor_id: str, page_set_json: Dict[str, Any],
                            page_set_hash: str, progress_total: int,
                            extraction_version: str, page_set_version: str) -> str:
        """Create a new snapshot."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            snapshot_data = {
                'competitor_id': competitor_id,
                'created_at': datetime.now().isoformat(),
                'page_count': progress_total,
                'status': 'queued',
                'progress_pages_done': 0,
                'progress_pages_total': progress_total,
                'started_at': datetime.now().isoformat(),
                'extraction_version': extraction_version,
                'page_set_version': page_set_version,
                'page_set_hash': page_set_hash,
                'page_set_json': page_set_json
            }

            result = self.client.table('snapshots').insert(snapshot_data).execute()
            snapshot_id = result.data[0]['id']

            logger.info(f"Snapshot created: {snapshot_id}")
            return snapshot_id

        except Exception as e:
            logger.error(f"Error creating snapshot: {e}")
            raise

    async def update_snapshot_status(self, snapshot_id: str, status: str,
                                   progress_done: Optional[int] = None,
                                   progress_total: Optional[int] = None,
                                   error_code: Optional[str] = None,
                                   error_message: Optional[str] = None,
                                   finished_at: Optional[datetime] = None) -> None:
        """Update snapshot status."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            update_data = {'status': status}

            if progress_done is not None:
                update_data['progress_pages_done'] = progress_done

            if progress_total is not None:
                update_data['progress_pages_total'] = progress_total

            if error_code is not None:
                update_data['error_code'] = error_code

            if error_message is not None:
                update_data['error_message'] = error_message

            if finished_at is not None:
                update_data['finished_at'] = finished_at.isoformat()

            self.client.table('snapshots').update(update_data).eq('id', snapshot_id).execute()

            logger.debug(f"Snapshot {snapshot_id} status updated: {status}")

        except Exception as e:
            logger.error(f"Error updating snapshot status: {e}")
            raise

    async def insert_or_update_page(self, snapshot_id: str, page_payload: Dict[str, Any]) -> str:
        """Insert or update a page."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Supabase uses UUIDs, so we let it generate the ID
            result = self.client.table('pages').insert(page_payload).execute()
            page_id = result.data[0]['id']

            logger.debug(f"Page saved: {page_id}")
            return page_id

        except Exception as e:
            logger.error(f"Error saving page: {e}")
            raise

    async def upsert_socials(self, competitor_id: str, socials: List[Dict[str, Any]]) -> None:
        """Insert or update social media links."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        if not socials:
            return

        try:
            for social in socials:
                social_data = {
                    'competitor_id': competitor_id,
                    'platform': social['platform'],
                    'handle': social['handle'],
                    'url': social['url'],
                    'discovered_at': datetime.now().isoformat(),
                    'source_url': social.get('source_url', '')
                }

                try:
                    self.client.table('socials').upsert(social_data, on_conflict='competitor_id,platform,handle').execute()
                except Exception as e:
                    logger.warning(f"Error saving social link {social}: {e}")
                    continue

            logger.debug(f"{len(socials)} social links saved for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Error saving social links: {e}")
            raise

    async def save_profile(self, competitor_id: str, snapshot_id: str, text: str) -> None:
        """Save or update a competitor profile."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            profile_data = {
                'competitor_id': competitor_id,
                'snapshot_id': snapshot_id,
                'created_at': datetime.now().isoformat(),
                'text': text
            }

            self.client.table('profiles').upsert(profile_data, on_conflict='competitor_id,snapshot_id').execute()

            logger.info(f"Profile saved for competitor {competitor_id}")

        except Exception as e:
            logger.error(f"Error saving profile: {e}")
            raise

    async def get_latest_snapshot_id(self, competitor_id: str) -> Optional[str]:
        """Get the most recent snapshot ID for a competitor."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            result = self.client.table('snapshots') \
                .select('id') \
                .eq('competitor_id', competitor_id) \
                .eq('status', 'done') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()

            if result.data:
                return result.data[0]['id']

            return None

        except Exception as e:
            logger.error(f"Error getting latest snapshot: {e}")
            return None

    async def get_pages_map(self, snapshot_id: str) -> Dict[str, Dict[str, Any]]:
        """Get a map of canonical_url -> page data for change detection."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            result = self.client.table('pages') \
                .select('id, canonical_url, sha256_text, text_path, raw_path') \
                .eq('snapshot_id', snapshot_id) \
                .execute()

            page_map = {}
            for row in result.data:
                page_map[row['canonical_url']] = {
                    'page_id': row['id'],
                    'sha256_text': row['sha256_text'],
                    'text_path': row['text_path'],
                    'raw_path': row['raw_path']
                }

            return page_map

        except Exception as e:
            logger.error(f"Error loading page map: {e}")
            return {}

    async def get_snapshot(self, snapshot_id: str, with_previews: bool = False,
                          preview_limit: int = 10) -> Optional[Dict[str, Any]]:
        """Get complete snapshot data including pages."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Get snapshot
            snapshot_result = self.client.table('snapshots') \
                .select('*') \
                .eq('id', snapshot_id) \
                .execute()

            if not snapshot_result.data:
                return None

            snapshot_data = snapshot_result.data[0]
            snapshot = {
                'id': snapshot_data['id'],
                'competitor_id': snapshot_data['competitor_id'],
                'created_at': snapshot_data['created_at'],
                'page_count': snapshot_data['page_count'],
                'notes': snapshot_data.get('notes'),
                'status': snapshot_data['status'],
                'progress_pages_done': snapshot_data['progress_pages_done'],
                'progress_pages_total': snapshot_data['progress_pages_total'],
                'started_at': snapshot_data.get('started_at'),
                'finished_at': snapshot_data.get('finished_at'),
                'error_code': snapshot_data.get('error_code'),
                'error_message': snapshot_data.get('error_message'),
                'extraction_version': snapshot_data.get('extraction_version'),
                'page_set_version': snapshot_data.get('page_set_version'),
                'page_set_hash': snapshot_data.get('page_set_hash'),
                'page_set_changed': snapshot_data.get('page_set_changed', False),
                'page_set_json': snapshot_data.get('page_set_json'),
                'pages': []
            }

            # Get pages
            pages_result = self.client.table('pages') \
                .select('*') \
                .eq('snapshot_id', snapshot_id) \
                .order('fetched_at') \
                .execute()

            pages = []
            for row in pages_result.data:
                page = {
                    'id': row['id'],
                    'url': row['url'],
                    'final_url': row['final_url'],
                    'status': row['status'],
                    'fetched_at': row['fetched_at'],
                    'via': row['via'],
                    'content_type': row['content_type'],
                    'raw_path': row['raw_path'],
                    'text_path': row['text_path'],
                    'sha256_text': row['sha256_text'],
                    'title': row['title'],
                    'meta_description': row['meta_description'],
                    'canonical_url': row['canonical_url'],
                    'changed': row['changed'],
                    'prev_page_id': row['prev_page_id'],
                    'raw_download_url': f"/api/pages/{row['id']}/raw",
                    'text_download_url': f"/api/pages/{row['id']}/text"
                }

                # Add text preview if requested and within limit
                if with_previews and len(pages) < preview_limit:
                    preview = await self.get_page_preview(row['id'], max_length=300)
                    if preview:
                        page['text_preview'] = preview['text_preview']

                pages.append(page)

            snapshot['pages'] = pages
            return snapshot

        except Exception as e:
            logger.error(f"Error loading snapshot: {e}")
            return None

    async def list_competitors(self) -> List[Dict[str, Any]]:
        """Get all competitors with their snapshots."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Get competitors
            competitors_result = self.client.table('competitors') \
                .select('*') \
                .order('created_at', desc=True) \
                .execute()

            competitors = []
            for comp_data in competitors_result.data:
                competitor = {
                    'id': comp_data['id'],
                    'name': comp_data['name'],
                    'base_url': comp_data['base_url'],
                    'created_at': comp_data['created_at'],
                    'url': comp_data['base_url'],  # for frontend compatibility
                    'snapshots': []
                }

                # Get snapshots for this competitor
                snapshots_result = self.client.table('snapshots') \
                    .select('id, created_at, page_count, notes, status, progress_pages_done, progress_pages_total') \
                    .eq('competitor_id', comp_data['id']) \
                    .order('created_at', desc=True) \
                    .execute()

                competitor['snapshots'] = [
                    {
                        'id': s['id'],
                        'created_at': s['created_at'],
                        'page_count': s['page_count'],
                        'notes': s.get('notes'),
                        'status': s['status'],
                        'progress_pages_done': s['progress_pages_done'],
                        'progress_pages_total': s['progress_pages_total'],
                        'base_url': comp_data['base_url']
                    }
                    for s in snapshots_result.data
                ]

                competitors.append(competitor)

            return competitors

        except Exception as e:
            logger.error(f"Error loading competitors: {e}")
            return []

    async def get_competitor(self, competitor_id: str) -> Optional[Dict[str, Any]]:
        """Get a single competitor with snapshots and socials."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Get competitor
            comp_result = self.client.table('competitors') \
                .select('*') \
                .eq('id', competitor_id) \
                .execute()

            if not comp_result.data:
                return None

            comp_data = comp_result.data[0]
            competitor = {
                'id': comp_data['id'],
                'name': comp_data['name'],
                'base_url': comp_data['base_url'],
                'created_at': comp_data['created_at'],
                'url': comp_data['base_url'],  # for frontend compatibility
                'snapshots': [],
                'socials': []
            }

            # Get snapshots
            snapshots_result = self.client.table('snapshots') \
                .select('id, created_at, page_count, notes') \
                .eq('competitor_id', competitor_id) \
                .order('created_at', desc=True) \
                .execute()

            competitor['snapshots'] = [
                {
                    'id': s['id'],
                    'created_at': s['created_at'],
                    'page_count': s['page_count'],
                    'notes': s.get('notes'),
                    'base_url': comp_data['base_url']
                }
                for s in snapshots_result.data
            ]

            # Get socials
            socials_result = self.client.table('socials') \
                .select('platform, handle, url, discovered_at, source_url') \
                .eq('competitor_id', competitor_id) \
                .execute()

            competitor['socials'] = [
                {
                    'platform': row['platform'],
                    'handle': row['handle'],
                    'url': row['url'],
                    'discovered_at': row['discovered_at'],
                    'source_url': row['source_url']
                }
                for row in socials_result.data
            ]

            return competitor

        except Exception as e:
            logger.error(f"Error loading competitor: {e}")
            return None

    async def download_page_raw(self, page_id: str) -> Optional[bytes]:
        """Download raw HTML content from Supabase Storage."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Get page data to find the path
            page_result = self.client.table('pages') \
                .select('raw_path') \
                .eq('id', page_id) \
                .execute()

            if not page_result.data or not page_result.data[0]['raw_path']:
                return None

            file_path = page_result.data[0]['raw_path']

            # Download from storage
            response = self.client.storage.from_(self.storage_bucket).download(file_path)

            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Storage download failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error downloading raw content for page {page_id}: {e}")
            return None

    async def download_page_text(self, page_id: str) -> Optional[bytes]:
        """Download normalized text content from Supabase Storage."""
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        try:
            # Get page data to find the path
            page_result = self.client.table('pages') \
                .select('text_path') \
                .eq('id', page_id) \
                .execute()

            if not page_result.data or not page_result.data[0]['text_path']:
                return None

            file_path = page_result.data[0]['text_path']

            # Download from storage
            response = self.client.storage.from_(self.storage_bucket).download(file_path)

            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Storage download failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error downloading text content for page {page_id}: {e}")
            return None

    async def get_page_preview(self, page_id: str, max_length: int = 300) -> Optional[Dict[str, Any]]:
        """Get text preview for a page."""
        text_content = await self.download_page_text(page_id)

        if text_content is None:
            return None

        try:
            text_str = text_content.decode('utf-8')
            return {
                'page_id': page_id,
                'text_preview': text_str[:max_length],
                'has_more': len(text_str) > max_length
            }
        except UnicodeDecodeError:
            return {
                'page_id': page_id,
                'text_preview': f"[Binary content, {len(text_content)} bytes]",
                'has_more': False
            }

    async def upload_raw_and_text(self, snapshot_id: str, page_id: str, html: str, text: str) -> Dict[str, str]:
        """
        Upload HTML and text content to Supabase Storage.

        Args:
            snapshot_id: The snapshot ID
            page_id: The page ID
            html: Raw HTML content
            text: Normalized text content

        Returns:
            Dict with 'raw_path' and 'text_path' for database storage
        """
        if not self.client:
            raise RuntimeError("Supabase client not initialized")

        raw_path = f"snapshots/{snapshot_id}/pages/{page_id}.html"
        text_path = f"snapshots/{snapshot_id}/pages/{page_id}.txt"

        try:
            # Upload HTML
            html_bytes = html.encode('utf-8')
            html_response = self.client.storage.from_(self.storage_bucket).upload(
                path=raw_path,
                file=html_bytes,
                file_options={"content-type": "text/html; charset=utf-8"}
            )

            if html_response.status_code not in [200, 201]:
                raise Exception(f"HTML upload failed: {html_response.status_code}")

            # Upload text
            text_bytes = text.encode('utf-8')
            text_response = self.client.storage.from_(self.storage_bucket).upload(
                path=text_path,
                file=text_bytes,
                file_options={"content-type": "text/plain; charset=utf-8"}
            )

            if text_response.status_code not in [200, 201]:
                raise Exception(f"Text upload failed: {text_response.status_code}")

            logger.debug(f"Files uploaded for page {page_id}: {raw_path}, {text_path}")

            return {
                'raw_path': raw_path,
                'text_path': text_path
            }

        except Exception as e:
            logger.error(f"Error uploading files for page {page_id}: {e}")
            raise
