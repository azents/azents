"""Provider enrollment and credential verifier primitives."""

import base64
import hashlib
import hmac
import secrets


class RuntimeProviderCredentialVerifier:
    """Create and verify one-time Provider enrollment and credential secrets."""

    _DOMAIN_LABEL = b"azents/runtime-provider-credential-verifier/v1"
    _SECRET_BYTES = 32

    def __init__(self, credential_encryption_key: str) -> None:
        """Derive a verifier key from deployment-rooted secret material.

        :param credential_encryption_key: Fernet root key configured for Azents.
        """
        root = base64.urlsafe_b64decode(credential_encryption_key.encode())
        self._key = hmac.new(root, self._DOMAIN_LABEL, hashlib.sha256).digest()

    def issue_secret(self) -> str:
        """Return a high-entropy plaintext secret that is never persisted."""
        return secrets.token_urlsafe(self._SECRET_BYTES)

    def verifier_for(self, secret: str) -> str:
        """Return the stable keyed verifier stored in durable persistence."""
        return hmac.new(self._key, secret.encode(), hashlib.sha256).hexdigest()

    def matches(self, secret: str, verifier: str) -> bool:
        """Compare a supplied plaintext secret to a stored verifier safely."""
        return hmac.compare_digest(self.verifier_for(secret), verifier)
