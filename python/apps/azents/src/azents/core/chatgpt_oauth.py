"""ChatGPT OAuth constants and session state."""

import enum
from typing import Final

CHATGPT_OAUTH_ISSUER = "https://auth.openai.com"
CHATGPT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_OAUTH_TOKEN_URL = f"{CHATGPT_OAUTH_ISSUER}/oauth/token"
CHATGPT_OAUTH_REVOKE_URL = f"{CHATGPT_OAUTH_ISSUER}/oauth/revoke"
CHATGPT_OAUTH_DEVICE_USER_CODE_URL = (
    f"{CHATGPT_OAUTH_ISSUER}/api/accounts/deviceauth/usercode"
)
CHATGPT_OAUTH_DEVICE_TOKEN_URL = f"{CHATGPT_OAUTH_ISSUER}/api/accounts/deviceauth/token"
CHATGPT_OAUTH_DEVICE_VERIFICATION_URL = f"{CHATGPT_OAUTH_ISSUER}/codex/device"
CHATGPT_OAUTH_DEVICE_REDIRECT_URI = f"{CHATGPT_OAUTH_ISSUER}/deviceauth/callback"
CHATGPT_OAUTH_BACKEND_BASE_URL = "https://chatgpt.com/backend-api/codex"
AZENTS_VERSION: Final = "0.1.0"
CHATGPT_OAUTH_PROTOCOL_VERSION: Final = "0.144.0"


def build_chatgpt_oauth_headers(*, account_id: str | None) -> dict[str, str]:
    """Build common ChatGPT backend client identity headers."""
    headers = {
        "originator": "azents",
        "user-agent": f"azents/{AZENTS_VERSION}",
    }
    if account_id is not None:
        headers["ChatGPT-Account-Id"] = account_id
    return headers


class ChatGPTOAuthConnectionMethod(enum.StrEnum):
    """ChatGPT OAuth connection method."""

    CALLBACK = "callback"
    DEVICE = "device"


class ChatGPTOAuthConnectionStatus(enum.StrEnum):
    """ChatGPT OAuth integration status."""

    CONNECTED = "connected"
    REFRESH_REQUIRED = "refresh_required"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DISABLED = "disabled"


class ChatGPTOAuthSessionStatus(enum.StrEnum):
    """ChatGPT OAuth session status."""

    PENDING = "pending"
    CONNECTED = "connected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
