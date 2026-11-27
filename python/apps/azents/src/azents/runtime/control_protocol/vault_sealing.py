"""Confidential Runner recipient sealing at the application boundary."""

import base64
import binascii
import json
from collections.abc import Mapping

from azents_runtime_control.vault_contract import (
    MAX_VAULT_CIPHERTEXT_BYTES,
    MAX_VAULT_FILE_BYTES,
    VaultOperationContext,
    VaultTransportError,
    decode_vault_base64,
    decode_vault_body,
    decode_vault_environment,
    encode_vault_body,
)
from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox
from pydantic import SecretStr


class VaultSealError(ValueError):
    """Value-free error at the sealing boundary."""


def seal_browser_input(value: SecretStr, recipient: str) -> str:
    """Seal a value for the current Browser fill recipient."""
    try:
        plaintext = value.get_secret_value().encode("utf-8")
        if len(plaintext) > 4096:
            raise ValueError
        key = base64.b64decode(recipient, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(key).decode("ascii") != recipient:
            raise ValueError
        return base64.urlsafe_b64encode(
            SealedBox(PublicKey(key)).encrypt(plaintext)
        ).decode("ascii")
    except ValueError, binascii.Error, CryptoError, TypeError:
        raise VaultSealError("Vault value or Browser recipient is invalid.") from None


def seal_process_environment(
    context: VaultOperationContext, values: Mapping[str, SecretStr], recipient: str
) -> str:
    """Seal exactly the secret assignments for this process start."""
    try:
        raw = json.dumps(
            {name: value.get_secret_value() for name, value in values.items()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(raw) > MAX_VAULT_CIPHERTEXT_BYTES:
            raise VaultTransportError("Invalid Vault environment.")
        decode_vault_environment(raw)
        key = PublicKey(decode_vault_base64(recipient, maximum_bytes=32))
        return base64.urlsafe_b64encode(
            SealedBox(key).encrypt(encode_vault_body(context, raw))
        ).decode("ascii")
    except ValueError, TypeError, CryptoError:
        raise VaultSealError("Vault environment could not be sealed.") from None


class FileVaultRecipient:
    """An application recipient owned by one file-read operation."""

    def __init__(self) -> None:
        self._key = PrivateKey.generate()

    @property
    def public_key(self) -> str:
        """Return the public part of this operation's keypair."""
        return base64.urlsafe_b64encode(bytes(self._key.public_key)).decode("ascii")

    def open_value(self, context: VaultOperationContext, ciphertext: str) -> SecretStr:
        """Return only a bound, complete bounded UTF-8 result."""
        try:
            raw = SealedBox(self._key).decrypt(
                decode_vault_base64(
                    ciphertext, maximum_bytes=MAX_VAULT_CIPHERTEXT_BYTES
                )
            )
            value = decode_vault_body(context, raw)
            if len(value) > MAX_VAULT_FILE_BYTES:
                raise VaultTransportError("Invalid Vault file result.")
            return SecretStr(value.decode("utf-8"))
        except ValueError, TypeError, CryptoError:
            raise VaultSealError("Vault file response is invalid.") from None
