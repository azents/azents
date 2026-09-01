"""Resource-bound Runtime Terminal ticket signing and verification."""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from azents.services.runtime_terminal.data import (
    RuntimeTerminalResource,
    RuntimeTerminalTicketClaims,
)

_TICKET_VERSION = "v1"


class RuntimeTerminalTicketInvalid(ValueError):
    """Raised when a Terminal ticket is malformed, expired, or inauthentic."""


class RuntimeTerminalTicketCodec(Protocol):
    """Encode and verify one opaque Terminal ticket."""

    def encode(self, claims: RuntimeTerminalTicketClaims) -> str:
        """Return an opaque signed ticket."""
        ...

    def decode(self, ticket: str, *, now: datetime) -> RuntimeTerminalTicketClaims:
        """Verify and decode current claims."""
        ...


class HmacRuntimeTerminalTicketCodec:
    """HMAC-SHA256 Terminal ticket codec with canonical JSON claims."""

    def __init__(self, secret: bytes) -> None:
        """Initialize a deployment-rooted ticket signer."""
        if len(secret) < 32:
            raise ValueError("Runtime Terminal ticket secret must be at least 32 bytes")
        self._key = hmac.new(
            secret,
            b"azents/runtime-terminal-ticket/v1",
            hashlib.sha256,
        ).digest()

    def encode(self, claims: RuntimeTerminalTicketClaims) -> str:
        """Return one URL-safe canonical signed ticket."""
        payload = {
            "version": _TICKET_VERSION,
            "ticket_id": claims.ticket_id,
            "user_id": claims.user_id,
            "authentication_session_id": claims.authentication_session_id,
            "workspace_id": claims.workspace_id,
            "resource": asdict(claims.resource),
            "intent": claims.intent,
            "issued_at": claims.issued_at.astimezone(UTC).isoformat(),
            "expires_at": claims.expires_at.astimezone(UTC).isoformat(),
        }
        encoded = _encode(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        signature = _encode(
            hmac.new(self._key, encoded.encode(), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}"

    def decode(self, ticket: str, *, now: datetime) -> RuntimeTerminalTicketClaims:
        """Verify signature, schema, and absolute lifetime."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Terminal ticket clock must be timezone-aware")
        if ticket != ticket.strip() or ticket.count(".") != 1:
            raise RuntimeTerminalTicketInvalid("Runtime Terminal ticket is invalid")
        encoded, signature = ticket.split(".", 1)
        expected = _encode(
            hmac.new(self._key, encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise RuntimeTerminalTicketInvalid("Runtime Terminal ticket is invalid")
        try:
            raw = json.loads(_decode(encoded))
            if not isinstance(raw, dict) or set(raw) != {
                "version",
                "ticket_id",
                "user_id",
                "authentication_session_id",
                "workspace_id",
                "resource",
                "intent",
                "issued_at",
                "expires_at",
            }:
                raise ValueError
            resource = raw["resource"]
            if not isinstance(resource, dict) or set(resource) != {
                "workspace_handle",
                "agent_id",
                "session_id",
            }:
                raise ValueError
            if raw["version"] != _TICKET_VERSION:
                raise ValueError
            claims = RuntimeTerminalTicketClaims(
                ticket_id=_required_string(raw, "ticket_id"),
                user_id=_required_string(raw, "user_id"),
                authentication_session_id=_required_string(
                    raw,
                    "authentication_session_id",
                ),
                workspace_id=_required_string(raw, "workspace_id"),
                resource=RuntimeTerminalResource(
                    workspace_handle=_required_string(resource, "workspace_handle"),
                    agent_id=_required_string(resource, "agent_id"),
                    session_id=_required_string(resource, "session_id"),
                ),
                intent=_required_string(raw, "intent"),
                issued_at=datetime.fromisoformat(_required_string(raw, "issued_at")),
                expires_at=datetime.fromisoformat(_required_string(raw, "expires_at")),
            )
        except (
            binascii.Error,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise RuntimeTerminalTicketInvalid(
                "Runtime Terminal ticket is invalid"
            ) from None
        if (
            claims.issued_at.tzinfo is None
            or claims.expires_at.tzinfo is None
            or claims.expires_at <= claims.issued_at
            or claims.intent != "open_or_attach"
            or now >= claims.expires_at
        ):
            raise RuntimeTerminalTicketInvalid("Runtime Terminal ticket is invalid")
        return claims


def _required_string(values: dict[str, object], key: str) -> str:
    value = values[key]
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode()
