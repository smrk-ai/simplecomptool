"""
Shared Types für Fetcher Module
"""

from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class FetchResult:
    """Standardisiertes Ergebnis eines Fetch-Vorgangs"""
    url: str
    final_url: str
    status: int
    headers: Dict[str, str]
    html: str
    fetched_at: str
    via: str  # "httpx" | "playwright"
    content_type: Optional[str] = None
