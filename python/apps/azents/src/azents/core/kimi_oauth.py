"""Kimi OAuth constants, compatibility headers, and session state."""

import enum
import os
import platform

KIMI_OAUTH_ISSUER = "https://auth.kimi.com"
# Public native-app client identity used by the official Kimi CLI device flow.
KIMI_OAUTH_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
KIMI_OAUTH_DEVICE_CODE_URL = f"{KIMI_OAUTH_ISSUER}/api/oauth/device_authorization"
KIMI_OAUTH_TOKEN_URL = f"{KIMI_OAUTH_ISSUER}/api/oauth/token"
KIMI_CODE_API_BASE_URL = "https://api.kimi.com/coding/v1"
KIMI_COMPATIBILITY_VERSION = "1.49.0"


def resolve_kimi_oauth_device_code_url() -> str:
    """Return the configured Kimi device authorization endpoint."""
    return os.environ.get("AZ_KIMI_OAUTH_DEVICE_CODE_URL", KIMI_OAUTH_DEVICE_CODE_URL)


def resolve_kimi_oauth_token_url() -> str:
    """Return the configured Kimi OAuth token endpoint."""
    return os.environ.get("AZ_KIMI_OAUTH_TOKEN_URL", KIMI_OAUTH_TOKEN_URL)


def resolve_kimi_code_api_base_url() -> str:
    """Return the configured Kimi Code API root."""
    return os.environ.get("AZ_KIMI_CODE_API_BASE_URL", KIMI_CODE_API_BASE_URL).rstrip(
        "/"
    )


def build_kimi_compatibility_headers(*, device_id: str) -> dict[str, str]:
    """Build the Kimi CLI-compatible request identity for one encrypted device."""
    version = os.environ.get(
        "AZ_KIMI_COMPATIBILITY_VERSION", KIMI_COMPATIBILITY_VERSION
    )
    os_version = " ".join(
        part for part in (platform.system(), platform.release()) if part
    )
    values = {
        "X-Msh-Platform": "kimi_cli",
        "X-Msh-Version": version,
        "X-Msh-Device-Name": "Azents",
        "X-Msh-Device-Model": "Azents Server",
        "X-Msh-Os-Version": os_version or "Unknown",
        "X-Msh-Device-Id": device_id,
    }
    return {name: _ascii_header_value(value) for name, value in values.items()}


def _ascii_header_value(value: str) -> str:
    """Return a non-empty ASCII HTTP header value."""
    normalized = value.encode("ascii", errors="ignore").decode("ascii").strip()
    return normalized or "unknown"


class KimiOAuthConnectionMethod(enum.StrEnum):
    """Kimi OAuth connection method."""

    DEVICE = "device"


class KimiOAuthConnectionStatus(enum.StrEnum):
    """Kimi OAuth integration status."""

    CONNECTED = "connected"
    REFRESH_REQUIRED = "refresh_required"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DISABLED = "disabled"


class KimiOAuthSessionStatus(enum.StrEnum):
    """Kimi OAuth session status."""

    PENDING = "pending"
    CONNECTED = "connected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
