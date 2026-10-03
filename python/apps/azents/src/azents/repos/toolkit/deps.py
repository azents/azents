"""Credential-aware Toolkit repository composition."""

from typing import Annotated

from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.repos.toolkit import ToolkitRepository


def get_toolkit_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ToolkitRepository:
    """Wire Toolkit credential access without exposing a cipher as request input."""
    return ToolkitRepository(cipher=cipher)
