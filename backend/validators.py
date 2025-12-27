"""
Input Validation Module

SECURITY: Validates user input to prevent injection attacks and SSRF vulnerabilities.
"""

from fastapi import HTTPException
import re
from urllib.parse import urlparse
from typing import Optional

# Private IP ranges (RFC 1918)
PRIVATE_IP_REGEX = r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.)'

# Cloud metadata service IPs
AWS_METADATA_IP = '169.254.169.254'
GCP_METADATA_IP = '169.254.169.254'
AZURE_METADATA_IP = '169.254.169.254'

# Localhost variants
LOCALHOST_NAMES = ['localhost', '0.0.0.0', '::1', '127.0.0.1']


def validate_scan_url(url: str) -> str:
    """
    Validates URL for Scan requests.

    SECURITY: Prevents SSRF (Server-Side Request Forgery) attacks by:
    - Blocking private IP ranges
    - Blocking localhost
    - Blocking cloud metadata services
    - Validating URL schema
    - Enforcing length limits

    Args:
        url: User-provided URL to scan

    Returns:
        Validated URL (unchanged if valid)

    Raises:
        HTTPException: If URL is invalid or dangerous

    Examples:
        >>> validate_scan_url("https://example.com")
        'https://example.com'

        >>> validate_scan_url("http://localhost:8000")
        HTTPException(400, "Localhost nicht erlaubt")

        >>> validate_scan_url("http://169.254.169.254/metadata")
        HTTPException(400, "Metadata-Service nicht erlaubt")
    """
    # Length check (prevent DoS via huge URLs)
    if not url or len(url) > 2048:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_URL_LENGTH",
                    "message": "URL muss zwischen 1-2048 Zeichen sein"
                }
            }
        )

    url = url.strip()

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_URL_FORMAT",
                    "message": f"Ungültiges URL-Format: {str(e)}"
                }
            }
        )

    # Schema validation (nur http/https erlaubt)
    if parsed.scheme and parsed.scheme not in ['http', 'https']:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_URL_SCHEME",
                    "message": f"Ungültiges URL-Schema: {parsed.scheme}. Nur http und https erlaubt."
                }
            }
        )

    # SSRF Protection: Hostname validation
    if parsed.hostname:
        hostname = parsed.hostname.lower()

        # Block localhost variants
        if hostname in LOCALHOST_NAMES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "LOCALHOST_NOT_ALLOWED",
                        "message": "Localhost-URLs sind aus Sicherheitsgründen nicht erlaubt"
                    }
                }
            )

        # Block cloud metadata services (AWS, GCP, Azure)
        if hostname in [AWS_METADATA_IP, GCP_METADATA_IP, AZURE_METADATA_IP]:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "METADATA_SERVICE_BLOCKED",
                        "message": "Zugriff auf Cloud-Metadata-Services nicht erlaubt"
                    }
                }
            )

        # Block private IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x)
        if re.match(PRIVATE_IP_REGEX, hostname):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "PRIVATE_IP_NOT_ALLOWED",
                        "message": "Private IP-Adressen sind aus Sicherheitsgründen nicht erlaubt"
                    }
                }
            )

        # Block link-local addresses (169.254.x.x)
        if hostname.startswith('169.254.'):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "LINK_LOCAL_NOT_ALLOWED",
                        "message": "Link-local IP-Adressen sind nicht erlaubt"
                    }
                }
            )

    return url


def validate_competitor_name(name: Optional[str]) -> Optional[str]:
    """
    Validates competitor name.

    Args:
        name: User-provided competitor name (optional)

    Returns:
        Validated name or None

    Raises:
        HTTPException: If name is invalid
    """
    if name is None:
        return None

    # Length check
    if len(name) > 255:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NAME_TOO_LONG",
                    "message": "Name darf maximal 255 Zeichen haben"
                }
            }
        )

    # Strip whitespace
    return name.strip()
