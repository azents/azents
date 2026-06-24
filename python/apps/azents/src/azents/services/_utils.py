"""Common utilities for auth/onboarding services."""

import secrets
import string

#: Verification code charset (uppercase letters + digits)
CODE_CHARSET = string.ascii_uppercase + string.digits

#: Default verification code expiration time (minutes)
DEFAULT_EXPIRE_MINUTES = 10

#: Workspace creation validity time after verification (minutes)
DEFAULT_VERIFICATION_VALID_MINUTES = 10


def generate_code(length: int = 6) -> str:
    """Create verification code."""
    return "".join(secrets.choice(CODE_CHARSET) for _ in range(length))


def generate_csrf_token() -> str:
    """Create CSRF token."""
    return secrets.token_hex(32)


def generate_refresh_token() -> str:
    """Create refresh token."""
    return secrets.token_hex(32)
