"""
Base Store Interface for Persistence Adapters

This module defines the abstract interface that all persistence backends must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime


class Store(ABC):
    """
    Abstract base class for persistence backends.

    All methods are async to support both local (SQLite) and remote (Supabase) operations.
    """

    @abstractmethod
    async def init(self) -> None:
        """Initialize the store (create tables, setup connections, etc.)"""
        pass

    @abstractmethod
    async def upsert_competitor(self, name: Optional[str], base_url: str) -> str:
        """
        Create or update a competitor by base_url.

        Returns:
            competitor_id (string)
        """
        pass

    @abstractmethod
    async def create_snapshot(self, competitor_id: str, page_set_json: Dict[str, Any],
                            page_set_hash: str, progress_total: int,
                            extraction_version: str, page_set_version: str) -> str:
        """
        Create a new snapshot.

        Args:
            competitor_id: The competitor this snapshot belongs to
            page_set_json: Page set configuration as JSON
            page_set_hash: Hash of the page set for change detection
            progress_total: Total number of pages to fetch
            extraction_version: Version of extraction logic
            page_set_version: Version of page set logic

        Returns:
            snapshot_id (string)
        """
        pass

    @abstractmethod
    async def update_snapshot_status(self, snapshot_id: str, status: str,
                                   progress_done: Optional[int] = None,
                                   progress_total: Optional[int] = None,
                                   error_code: Optional[str] = None,
                                   error_message: Optional[str] = None,
                                   finished_at: Optional[datetime] = None) -> None:
        """
        Update snapshot status and progress information.
        """
        pass

    @abstractmethod
    async def insert_or_update_page(self, snapshot_id: str, page_payload: Dict[str, Any]) -> str:
        """
        Insert or update a page in the snapshot.

        Args:
            snapshot_id: The snapshot this page belongs to
            page_payload: Dict containing all page data:
                - url, final_url, canonical_url
                - status, fetched_at, via, content_type
                - raw_path, text_path, sha256_text
                - title, meta_description
                - changed, prev_page_id, normalized_len, extraction_version

        Returns:
            page_id (string)
        """
        pass

    @abstractmethod
    async def upsert_socials(self, competitor_id: str, socials: List[Dict[str, Any]]) -> None:
        """
        Insert or update social media links for a competitor.

        Args:
            socials: List of dicts with platform, handle, url
        """
        pass

    @abstractmethod
    async def save_profile(self, competitor_id: str, snapshot_id: str, text: str) -> None:
        """
        Save or update a competitor profile.
        """
        pass

    @abstractmethod
    async def get_latest_snapshot_id(self, competitor_id: str) -> Optional[str]:
        """
        Get the most recent snapshot ID for a competitor.

        Returns:
            snapshot_id or None if no snapshots exist
        """
        pass

    @abstractmethod
    async def get_pages_map(self, snapshot_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get a map of canonical_url -> page data for change detection.

        Returns:
            Dict[canonical_url, {
                'page_id': str,
                'sha256_text': str,
                'raw_path': str,
                'text_path': str
            }]
        """
        pass

    @abstractmethod
    async def get_snapshot(self, snapshot_id: str, with_previews: bool = False,
                          preview_limit: int = 10) -> Optional[Dict[str, Any]]:
        """
        Get complete snapshot data including pages.

        Returns:
            Snapshot DTO or None if not found
        """
        pass

    @abstractmethod
    async def list_competitors(self) -> List[Dict[str, Any]]:
        """
        Get all competitors with their snapshots.
        """
        pass

    @abstractmethod
    async def get_competitor(self, competitor_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single competitor with snapshots and socials.
        """
        pass

    @abstractmethod
    async def download_page_raw(self, page_id: str) -> Optional[bytes]:
        """
        Download raw HTML content for a page.

        Returns:
            HTML bytes or None if not found
        """
        pass

    @abstractmethod
    async def download_page_text(self, page_id: str) -> Optional[bytes]:
        """
        Download normalized text content for a page.

        Returns:
            Text bytes or None if not found
        """
        pass

    @abstractmethod
    async def get_page_preview(self, page_id: str, max_length: int = 300) -> Optional[Dict[str, Any]]:
        """
        Get text preview for a page.

        Returns:
            Dict with text_preview and has_more flag
        """
        pass
