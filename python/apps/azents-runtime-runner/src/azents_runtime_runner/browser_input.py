"""Process-lifetime recipient key for confidential Browser field input."""

import base64
import binascii

from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, SealedBox

PUBLIC_KEY_ENV = "AZENTS_BROWSER_INPUT_PUBLIC_KEY"
MAX_PLAINTEXT_BYTES = 4096
MAX_ENCODED_CIPHERTEXT = 5528


class BrowserInputError(ValueError):
    """Confidential input cannot be decoded with the current process key."""


class BrowserInputKey:
    """Hold a private key in process memory without a data-bearing repr."""

    def __init__(self) -> None:
        self._key = PrivateKey.generate()

    @property
    def public_key(self) -> str:
        """Return the command-safe recipient public key."""
        return base64.urlsafe_b64encode(bytes(self._key.public_key)).decode("ascii")

    def decrypt(self, encoded: str) -> str:
        """Validate bounded canonical ciphertext and decrypt without value errors."""
        try:
            if not 64 <= len(encoded) <= MAX_ENCODED_CIPHERTEXT:
                raise ValueError
            ciphertext = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if (
                not 48 <= len(ciphertext) <= MAX_PLAINTEXT_BYTES + 48
                or base64.urlsafe_b64encode(ciphertext).decode("ascii") != encoded
            ):
                raise ValueError
            return SealedBox(self._key).decrypt(ciphertext).decode("utf-8")
        except ValueError, binascii.Error, CryptoError:
            raise BrowserInputError("Browser encrypted input is invalid") from None
