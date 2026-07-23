"""Runtime Runner credential signing and verification primitives."""

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass

_CREDENTIAL_ID_LABEL = b"credential-id"


class RuntimeRunnerCredentialInvalid(ValueError):
    """Raised when a Runtime Runner credential is malformed or invalid."""


@dataclass(frozen=True)
class RuntimeRunnerIssuedCredential:
    """Plaintext credential and its non-secret diagnostic identifier."""

    token: str
    credential_id: str


@dataclass(frozen=True)
class RuntimeRunnerCredential:
    """Verified Runtime Runner credential claims."""

    credential_id: str
    runtime_id: str
    desired_generation: int


class RuntimeRunnerCredentialVerifier:
    """Issue and verify stateless Runtime-bound Runner credentials."""

    _DOMAIN_LABEL = b"azents/runtime-runner-credential/v1"
    _VERSION = "v1"
    _ROOT_BYTES = 32

    def __init__(self, credential_encryption_key: str) -> None:
        """Derive a domain-separated signing key from deployment root material."""
        try:
            root = base64.b64decode(
                credential_encryption_key.encode(),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid credential encryption key") from exc
        if len(root) != self._ROOT_BYTES:
            raise ValueError("Invalid credential encryption key")
        self._key = hmac.new(root, self._DOMAIN_LABEL, hashlib.sha256).digest()

    def issue(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
    ) -> RuntimeRunnerIssuedCredential:
        """Issue a credential bound to one Runtime desired-state generation."""
        credential_id = self.credential_id(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )
        payload = ".".join(
            (
                self._VERSION,
                credential_id,
                _encode(runtime_id.encode()),
                str(desired_generation),
            )
        )
        signature = _encode(
            hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
        )
        return RuntimeRunnerIssuedCredential(
            token=f"{payload}.{signature}",
            credential_id=credential_id,
        )

    def credential_id(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
    ) -> str:
        """Return the non-secret identifier for Runtime Runner evidence."""
        _validate_claims(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )
        return self._credential_id(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )

    def verify(self, token: str) -> RuntimeRunnerCredential:
        """Verify a credential and return its authenticated claims."""
        if token != token.strip():
            raise RuntimeRunnerCredentialInvalid("Invalid Runtime Runner credential")
        parts = token.split(".")
        if len(parts) != 5 or parts[0] != self._VERSION:
            raise RuntimeRunnerCredentialInvalid("Invalid Runtime Runner credential")
        _version, credential_id, encoded_runtime_id, generation_value, signature = parts
        payload = ".".join(parts[:4])
        expected_signature = _encode(
            hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected_signature):
            raise RuntimeRunnerCredentialInvalid("Invalid Runtime Runner credential")
        try:
            runtime_id = _decode(encoded_runtime_id).decode()
            desired_generation = int(generation_value)
        except binascii.Error, ValueError, UnicodeDecodeError:
            raise RuntimeRunnerCredentialInvalid(
                "Invalid Runtime Runner credential"
            ) from None
        if generation_value != str(desired_generation):
            raise RuntimeRunnerCredentialInvalid("Invalid Runtime Runner credential")
        try:
            _validate_claims(
                runtime_id=runtime_id,
                desired_generation=desired_generation,
            )
        except ValueError:
            raise RuntimeRunnerCredentialInvalid(
                "Invalid Runtime Runner credential"
            ) from None
        expected_credential_id = self._credential_id(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )
        if not hmac.compare_digest(credential_id, expected_credential_id):
            raise RuntimeRunnerCredentialInvalid("Invalid Runtime Runner credential")
        return RuntimeRunnerCredential(
            credential_id=credential_id,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )

    def _credential_id(
        self,
        *,
        runtime_id: str,
        desired_generation: int,
    ) -> str:
        claims = "\0".join((runtime_id, str(desired_generation))).encode()
        digest = hmac.new(
            self._key,
            _CREDENTIAL_ID_LABEL + b"\0" + claims,
            hashlib.sha256,
        ).digest()
        return _encode(digest[:16])


def _validate_claims(*, runtime_id: str, desired_generation: int) -> None:
    if not runtime_id:
        raise ValueError("Runtime ID is required")
    if desired_generation < 0:
        raise ValueError("Runtime desired generation must not be negative")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}".encode(),
        altchars=b"-_",
        validate=True,
    )
