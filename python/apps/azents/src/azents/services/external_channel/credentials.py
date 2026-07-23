"""Encrypted External Channel credential serialization helpers."""

from dataclasses import dataclass

from pydantic import TypeAdapter

from azents.core.crypto import CredentialCipher
from azents.services.external_channel.data import (
    ExternalChannelConnectionCredentials,
    ExternalChannelCredentialSnapshot,
    SlackConnectionCredentials,
)

_credentials_adapter = TypeAdapter(ExternalChannelConnectionCredentials)


@dataclass(frozen=True)
class ExternalChannelCredentialsCodec:
    """Serialize validated credentials through an injected CredentialCipher."""

    cipher: CredentialCipher

    def encrypt(self, credentials: ExternalChannelConnectionCredentials) -> str:
        """Return encrypted JSON for validated provider credentials."""
        return self.cipher.encrypt(credentials.model_dump_json())

    def decrypt(self, ciphertext: str) -> ExternalChannelConnectionCredentials:
        """Decrypt and validate one persisted provider credential payload."""
        return _credentials_adapter.validate_json(self.cipher.decrypt(ciphertext))

    @staticmethod
    def snapshot(
        credentials: ExternalChannelConnectionCredentials,
    ) -> ExternalChannelCredentialSnapshot:
        """Return a credential-presence snapshot that contains no secret values."""
        match credentials:
            case SlackConnectionCredentials(app_token=app_token):
                fields = ["bot_token", "signing_secret"]
                if app_token is not None:
                    fields.append("app_token")
                return ExternalChannelCredentialSnapshot(
                    provider=credentials.provider,
                    configured_fields=tuple(fields),
                )
