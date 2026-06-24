"""JWT token creation and verification.

Provides access token create/verify utilities and WebSocket ticket issue/verify
utilities.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from azents.core.config import JWTConfig

# WebSocket ticket validity in seconds
WS_TICKET_TTL_SECONDS = 30


@dataclass
class AccessTokenPayload:
    """Access Token payload structure."""

    user_id: str  # sub claim
    session_id: str  # sid claim
    exp: int  # Expiration time (Unix timestamp)
    iat: int  # Issued-at time (Unix timestamp)
    elevated: bool = False  # elv claim, whether step-up authentication is active


class InvalidTokenError(Exception):
    """Invalid token."""

    pass


class ExpiredTokenError(InvalidTokenError):
    """Expired token."""

    pass


def create_access_token(
    config: JWTConfig,
    user_id: str,
    session_id: str,
    expires_delta: timedelta | None = None,
    *,
    elevated: bool = False,
) -> str:
    """Create Access Token.

    :param config: JWT settings
    :param user_id: User ID
    :param session_id: Session ID
    :param expires_delta: Expiration time; defaults from config
    :param elevated: Whether step-up authentication is active
    :return: JWT string
    """
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(minutes=config.access_token_expire_minutes)
    expire = now + expires_delta

    payload: dict[str, object] = {
        "sub": user_id,
        "sid": session_id,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }

    if elevated:
        payload["elv"] = True

    return jwt.encode(payload, config.secret_key, algorithm=config.algorithm)


def decode_access_token(config: JWTConfig, token: str) -> AccessTokenPayload:
    """Decode and verify Access Token.

    :param config: JWT settings
    :param token: JWT string
    :return: Decoded payload
    :raises ExpiredTokenError: When token is expired
    :raises InvalidTokenError: When token is invalid
    """
    try:
        payload = jwt.decode(
            token,
            config.secret_key,
            algorithms=[config.algorithm],
            options={"require": ["sub", "sid", "exp", "iat"]},
        )
        return AccessTokenPayload(
            user_id=payload["sub"],
            session_id=payload["sid"],
            exp=payload["exp"],
            iat=payload["iat"],
            elevated=payload.get("elv", False),
        )
    except jwt.ExpiredSignatureError:
        raise ExpiredTokenError("Token has expired") from None
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"Invalid token: {e}") from None


# ---------------------------------------------------------------------------
# WebSocket ticket, HMAC-signature-based and stateless
# ---------------------------------------------------------------------------


@dataclass
class WsTicketPayload:
    """WebSocket ticket payload structure."""

    user_id: str
    session_id: str  # Authentication session ID


def _sign_ticket(payload: str, secret: str) -> str:
    """Create HMAC-SHA256 signature for payload, truncated to 16 bytes."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def create_ws_ticket(config: JWTConfig, user_id: str, session_id: str) -> str:
    """Create a short-lived HMAC ticket for WebSocket connections.

    Format: ``{user_id}.{session_id}.{exp_ts}.{signature}``

    :param config: JWT settings (uses secret_key as HMAC key)
    :param user_id: User ID
    :param session_id: Authentication session ID
    :return: Signed ticket string
    """
    exp = int(time.time()) + WS_TICKET_TTL_SECONDS
    payload = f"{user_id}.{session_id}.{exp}"
    sig = _sign_ticket(payload, config.secret_key)
    return f"{payload}.{sig}"


def verify_ws_ticket(config: JWTConfig, ticket: str) -> WsTicketPayload:
    """Verify WebSocket ticket.

    :param config: JWT settings (uses secret_key as HMAC key)
    :param ticket: Ticket string
    :return: Verified payload
    :raises ExpiredTokenError: Ticket expired
    :raises InvalidTokenError: Signature mismatch or format error
    """
    parts = ticket.split(".")
    if len(parts) != 4:
        raise InvalidTokenError("Invalid ticket format")

    user_id, session_id, exp_str, sig = parts

    # Verify signature
    payload = f"{user_id}.{session_id}.{exp_str}"
    expected_sig = _sign_ticket(payload, config.secret_key)
    if not hmac.compare_digest(sig, expected_sig):
        raise InvalidTokenError("Invalid ticket signature")

    # Verify expiration
    try:
        exp = int(exp_str)
    except ValueError:
        raise InvalidTokenError("Invalid ticket expiration") from None

    if time.time() > exp:
        raise ExpiredTokenError("Ticket has expired")

    return WsTicketPayload(user_id=user_id, session_id=session_id)
