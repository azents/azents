"""xAI OAuth constants and session state."""

import enum
import os

XAI_OAUTH_ISSUER = "https://auth.x.ai"
# Public native-app client identity used by the Grok CLI OAuth flow.
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_OAUTH_DEVICE_CODE_URL = f"{XAI_OAUTH_ISSUER}/oauth2/device/code"
XAI_OAUTH_TOKEN_URL = f"{XAI_OAUTH_ISSUER}/oauth2/token"
XAI_OAUTH_SCOPE = "openid profile email offline_access api:access grok-cli:access"
XAI_USAGE_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
XAI_USAGE_CLIENT_VERSION = "0.2.105"


def resolve_xai_usage_base_url() -> str:
    """Return the configured xAI CLI proxy usage endpoint."""
    return os.environ.get("AZ_XAI_USAGE_BASE_URL", XAI_USAGE_BASE_URL).rstrip("/")


def resolve_xai_oauth_device_code_url() -> str:
    """Return the configured xAI OAuth device-code endpoint."""
    return os.environ.get("AZ_XAI_OAUTH_DEVICE_CODE_URL", XAI_OAUTH_DEVICE_CODE_URL)


def resolve_xai_oauth_token_url() -> str:
    """Return the configured xAI OAuth token endpoint."""
    return os.environ.get("AZ_XAI_OAUTH_TOKEN_URL", XAI_OAUTH_TOKEN_URL)


class XaiOAuthConnectionMethod(enum.StrEnum):
    """xAI OAuth connection method."""

    DEVICE = "device"


class XaiOAuthConnectionStatus(enum.StrEnum):
    """xAI OAuth integration status."""

    CONNECTED = "connected"
    REFRESH_REQUIRED = "refresh_required"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    ENTITLEMENT_DENIED = "entitlement_denied"
    DISABLED = "disabled"


class XaiOAuthSessionStatus(enum.StrEnum):
    """xAI OAuth session status."""

    PENDING = "pending"
    CONNECTED = "connected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
