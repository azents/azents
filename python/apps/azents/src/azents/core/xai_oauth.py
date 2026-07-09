"""xAI OAuth constants and session state."""

import enum

XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_OAUTH_DEVICE_CODE_URL = f"{XAI_OAUTH_ISSUER}/oauth2/device/code"
XAI_OAUTH_TOKEN_URL = f"{XAI_OAUTH_ISSUER}/oauth2/token"
XAI_OAUTH_SCOPE = "openid profile email offline_access api:access grok-cli:access"
XAI_OAUTH_BACKEND_BASE_URL = "https://api.x.ai/v1"


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
