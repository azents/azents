"""LLM Provider Integration repository dependencies."""

from typing import Annotated

from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository


def get_llm_provider_integration_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """Create LLM provider integration repository."""
    return LLMProviderIntegrationRepository(cipher=cipher)
