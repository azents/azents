"""Runner-only confidential Vault transport endpoints."""

import base64
import os
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

from azents_runtime_control.runner import RunnerOperationEnvelope
from azents_runtime_control.vault_contract import (
    MAX_VAULT_CIPHERTEXT_BYTES,
    MAX_VAULT_FILE_BYTES,
    VAULT_FILE_READ,
    VAULT_PROCESS_START,
    VaultOperationContext,
    VaultTransportError,
    decode_vault_base64,
    decode_vault_body,
    decode_vault_environment,
    encode_vault_body,
)
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox


def vault_operation_context(
    operation: RunnerOperationEnvelope,
) -> VaultOperationContext:
    """Require a live, exactly identified confidential operation."""
    kind = operation.operation_type
    if (
        (kind != VAULT_FILE_READ and kind != VAULT_PROCESS_START)
        or operation.deadline_at is None
        or operation.deadline_at <= datetime.now(UTC)
        or operation.owner_session_id is None
    ):
        raise VaultTransportError("Vault operation is unavailable.")
    return VaultOperationContext(
        kind,
        operation.runtime_id,
        operation.runner_generation,
        operation.owner_session_id,
        operation.request_id,
        operation.deadline_at,
    )


class VaultRecipient:
    """Dedicated Runner-process private key for CLI values."""

    def __init__(self) -> None:
        self._key = PrivateKey.generate()

    @property
    def public_key(self) -> str:
        """Advertise only the recipient public key."""
        return base64.urlsafe_b64encode(bytes(self._key.public_key)).decode("ascii")

    def open_environment(
        self, operation: RunnerOperationEnvelope, ciphertext: str
    ) -> dict[str, str]:
        """Check the operation binding and validate the environment."""
        context = vault_operation_context(operation)
        try:
            body = SealedBox(self._key).decrypt(
                decode_vault_base64(
                    ciphertext, maximum_bytes=MAX_VAULT_CIPHERTEXT_BYTES
                )
            )
        except CryptoError, ValueError, TypeError:
            raise VaultTransportError("Invalid Vault environment.") from None
        return decode_vault_environment(decode_vault_body(context, body))


def read_vault_file(path: Path, cancelled: threading.Event) -> bytes:
    """Read no more than the full-value limit plus one byte from a regular file."""
    if cancelled.is_set():
        raise VaultTransportError("Vault file read cancelled.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise VaultTransportError("Vault source is not a readable regular file.")
        data = bytearray()
        while len(data) <= MAX_VAULT_FILE_BYTES:
            if cancelled.is_set():
                raise VaultTransportError("Vault file read cancelled.")
            chunk = os.read(fd, MAX_VAULT_FILE_BYTES + 1 - len(data))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise VaultTransportError("Vault file is too large.")
    finally:
        os.close(fd)


def seal_vault_file(
    operation: RunnerOperationEnvelope, data: bytes, recipient: str
) -> str:
    """Seal complete file bytes to the originating application operation."""
    context = vault_operation_context(operation)
    try:
        key = PublicKey(decode_vault_base64(recipient, maximum_bytes=32))
        return base64.urlsafe_b64encode(
            SealedBox(key).encrypt(encode_vault_body(context, data))
        ).decode("ascii")
    except ValueError, TypeError, CryptoError:
        raise VaultTransportError("Vault file result could not be sealed.") from None
