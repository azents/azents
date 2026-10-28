"""System-owned inference bearer lifecycle, independent of provider credentials."""

import datetime
import hashlib
import secrets
from dataclasses import dataclass

TOKEN_LIFETIME = datetime.timedelta(hours=1)
TOKEN_HANDOVER = datetime.timedelta(minutes=5)


class LLMAccessDenied(Exception):
    """No currently valid Agent-scoped access was established."""


class LLMTokenConflict(Exception):
    """The supply's expected current token is no longer current."""


class LLMTargetDenied(Exception):
    """No authorized matching target; do not expose foreign target existence."""


@dataclass(frozen=True)
class TokenState:
    token_id: str
    issued_at: datetime.datetime
    expires_at: datetime.datetime
    handover_until: datetime.datetime | None
    revoked_at: datetime.datetime | None


@dataclass(frozen=True)
class SupplyState:
    supply_id: str
    agent_id: str
    subject: str
    issuer: str
    current_token_id: str | None
    revoked_at: datetime.datetime | None
    tokens: tuple[TokenState, ...]


@dataclass(frozen=True)
class GeneratedLLMToken:
    """A transient secret whose digest alone is persisted."""

    value: str

    def __repr__(self) -> str:
        return "GeneratedLLMToken(value=<redacted>)"

    @property
    def digest(self) -> str:
        return token_digest(self.value)


def generate_token() -> GeneratedLLMToken:
    """Generate 256 bits of bearer entropy without embedding authority."""
    return GeneratedLLMToken(secrets.token_urlsafe(32))


def token_digest(value: str) -> str:
    """Hash bounded opaque input for lookup, never a provider credential."""
    if not value or len(value) > 512:
        raise LLMAccessDenied("Invalid inference credential.")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def handover_deadline(
    *, original_expiry: datetime.datetime, now: datetime.datetime
) -> datetime.datetime:
    """Never extend the previous credential's original lifetime."""
    return min(original_expiry, now + TOKEN_HANDOVER)
