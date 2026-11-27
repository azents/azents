"""Bounded plaintext format used only at confidential transport endpoints."""

import base64
import binascii
import dataclasses
import json
import re
from datetime import datetime
from typing import Literal

BROWSER_VAULT_RECIPIENT_CAPABILITY = "browser.vault_recipient"
BROWSER_VAULT_PUBLIC_KEY_METADATA = "browser_vault_public_key"
VAULT_RUNTIME_CAPABILITY = "vault.runtime"
VAULT_RUNTIME_PUBLIC_KEY_METADATA = "vault_runtime_public_key"
VAULT_PROCESS_START = "vault.process_start"
VAULT_FILE_READ = "vault.file_read"
MAX_VAULT_FILE_BYTES = 32768
MAX_VAULT_PLAINTEXT_BYTES = 131072
_SEALED_BOX_OVERHEAD = 48
MAX_VAULT_CIPHERTEXT_BYTES = MAX_VAULT_PLAINTEXT_BYTES + _SEALED_BOX_OVERHEAD
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class VaultTransportError(ValueError):
    """Fixed error for invalid confidential transport evidence."""


@dataclasses.dataclass(frozen=True)
class VaultOperationContext:
    """Exact identity that a recipient checks before using the sealed value."""

    operation: Literal["vault.process_start", "vault.file_read"]
    runtime_id: str
    runner_generation: int
    session_id: str
    request_id: str
    deadline: datetime

    def binding(self) -> bytes:
        """Encode an unambiguous versioned wire domain and operation identity."""
        return (
            json.dumps(
                [
                    "azents-vault-v1",
                    "to-runner" if self.operation == VAULT_PROCESS_START else "to-app",
                    self.operation,
                    self.runtime_id,
                    self.runner_generation,
                    self.session_id,
                    self.request_id,
                    self.deadline.isoformat(timespec="microseconds"),
                ],
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            + b"\n"
        )


def encode_vault_body(context: VaultOperationContext, data: bytes) -> bytes:
    """Bind bytes before encryption without an ambiguous field delimiter."""
    result = context.binding() + data
    if len(result) > MAX_VAULT_PLAINTEXT_BYTES:
        raise VaultTransportError("Vault transport input exceeds the allowed size.")
    return result


def decode_vault_body(context: VaultOperationContext, plaintext: bytes) -> bytes:
    """Check that decrypted bytes belong to this exact operation."""
    binding = context.binding()
    if len(plaintext) > MAX_VAULT_PLAINTEXT_BYTES or not plaintext.startswith(binding):
        raise VaultTransportError("Invalid Vault transport context.")
    return plaintext[len(binding) :]


def decode_vault_base64(encoded: str, *, maximum_bytes: int) -> bytes:
    """Decode strictly bounded and canonical URL-safe Base64."""
    if len(encoded) > ((maximum_bytes + 2) // 3) * 4:
        raise VaultTransportError("Invalid Vault transport encoding.")
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if (
            not 0 < len(decoded) <= maximum_bytes
            or base64.urlsafe_b64encode(decoded).decode("ascii") != encoded
        ):
            raise ValueError
        return decoded
    except ValueError, binascii.Error:
        raise VaultTransportError("Invalid Vault transport encoding.") from None


def vault_environment_name_valid(name: str) -> bool:
    """Accept an explicit ordinary portable environment variable name."""
    return bool(0 < len(name) <= 255 and _ENV_NAME.fullmatch(name))


def decode_vault_environment(data: bytes) -> dict[str, str]:
    """Validate a closed process environment map from decrypted data."""
    try:
        raw: object = json.loads(data.decode("utf-8"))
    except ValueError, RecursionError:
        raise VaultTransportError("Invalid Vault environment.") from None
    if not isinstance(raw, dict) or not 0 < len(raw) <= 64:
        raise VaultTransportError("Invalid Vault environment.")
    result: dict[str, str] = {}
    for name, value in raw.items():
        if (
            not isinstance(name, str)
            or not vault_environment_name_valid(name)
            or not isinstance(value, str)
            or "\0" in value
        ):
            raise VaultTransportError("Invalid Vault environment.")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise VaultTransportError("Invalid Vault environment.") from None
        result[name] = value
    return result
