"""Purpose-separated proof for the API's exact connection-bound Browser OPEN."""

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from azents_runtime_control.browser_source_contract import (
    BROWSER_SOURCE_AUDIENCE,
    BROWSER_SOURCE_OPERATION,
    BrowserSourceCredentialRequest,
)
from pydantic import BaseModel, ConfigDict, StrictStr

_DOMAIN = b"azents/runtime-browser-source-proof/v1"
_PREFIX = "brs1"


class _BrowserSourceProof(BaseModel):
    """Closed string-only signed proof, before temporal and scope validation."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True
    )

    audience: StrictStr
    operation: StrictStr
    service_identity: StrictStr
    issued_at: StrictStr
    expires_at: StrictStr
    request_sha256: StrictStr


class RuntimeBrowserSourceCredentialInvalid(ValueError):
    """A malformed, altered, wrong-purpose or expired source proof."""


def _fail() -> None:
    raise RuntimeBrowserSourceCredentialInvalid("Browser source credential is invalid")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class RuntimeBrowserSourceCredentialVerifier:
    """Derive a Browser-only key from already-provisioned deployment root material."""

    def __init__(
        self, credential_encryption_key: str, *, clock: Callable[[], datetime]
    ) -> None:
        try:
            root = base64.b64decode(
                credential_encryption_key.encode("ascii"), altchars=b"-_", validate=True
            )
        except (binascii.Error, UnicodeError, ValueError) as exc:
            raise ValueError("Invalid credential encryption key") from exc
        if len(root) != 32:
            raise ValueError("Invalid credential encryption key")
        self._key = hmac.new(root, _DOMAIN, hashlib.sha256).digest()
        self.clock = clock

    def issue(self, request: BrowserSourceCredentialRequest) -> str:
        """Sign one exact challenge/Hello/OPEN; no durable nonce or user grant."""
        now = self.clock()
        request.validate(now)
        expires = min(request.challenge_deadline_at, now + timedelta(seconds=30))
        payload = json.dumps(
            {
                "audience": BROWSER_SOURCE_AUDIENCE,
                "operation": BROWSER_SOURCE_OPERATION,
                "service_identity": "azents-api",
                "issued_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "request_sha256": request.digest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        encoded = _encode(payload)
        signature = _encode(
            hmac.new(self._key, encoded.encode(), hashlib.sha256).digest()
        )
        return f"{_PREFIX}.{encoded}.{signature}"

    def verify(
        self, credential: str, *, request: BrowserSourceCredentialRequest
    ) -> None:
        """Verify exact once-connection scope; the RPC consumes its own challenge."""
        now = self.clock()
        try:
            request.validate(now)
            if not 0 < len(credential) <= 4096 or credential != credential.strip():
                _fail()
            prefix, encoded, signature = credential.split(".")
            expected = _encode(
                hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if prefix != _PREFIX or not hmac.compare_digest(signature, expected):
                _fail()
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
            payload = _BrowserSourceProof.model_validate(json.loads(decoded))
            issued = datetime.fromisoformat(payload.issued_at)
            expires = datetime.fromisoformat(payload.expires_at)
            if (
                payload.audience != BROWSER_SOURCE_AUDIENCE
                or payload.operation != BROWSER_SOURCE_OPERATION
                or payload.service_identity != "azents-api"
                or not hmac.compare_digest(payload.request_sha256, request.digest())
                or issued.tzinfo is None
                or expires.tzinfo is None
                or issued > now + timedelta(seconds=5)
                or not issued < expires <= issued + timedelta(seconds=30)
                or expires > request.challenge_deadline_at
                or now >= expires
            ):
                _fail()
        except ValueError, TypeError, KeyError, UnicodeError, binascii.Error:
            _fail()


@dataclass(frozen=True)
class RuntimeBrowserSourceCredentialSupplier:
    """API-only proof supplier using existing root provisioning."""

    verifier: RuntimeBrowserSourceCredentialVerifier

    async def __call__(self, request: BrowserSourceCredentialRequest) -> str:
        return self.verifier.issue(request)
