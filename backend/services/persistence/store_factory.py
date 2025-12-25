"""
Store Factory

Creates the appropriate persistence store based on configuration.
"""

import os
import logging
from typing import Optional

from .base import Store
from .sqlite_store import SQLiteStore
from .supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


def get_store() -> Store:
    """
    Factory function to create the appropriate store based on configuration.

    Returns:
        Store instance (SQLiteStore or SupabaseStore)
    """
    backend = os.getenv("PERSISTENCE_BACKEND", "sqlite").lower()

    if backend == "sqlite":
        logger.info("Using SQLite persistence backend")
        store = SQLiteStore()

    elif backend == "supabase":
        logger.info("Using Supabase persistence backend")

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        storage_bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "snapshots")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "Supabase backend requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables"
            )

        store = SupabaseStore(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            storage_bucket=storage_bucket
        )

    else:
        raise ValueError(f"Unknown persistence backend: {backend}. Supported: sqlite, supabase")

    # Store wird später in main.py initialisiert
    return store
