"""Runtime Provider Control dependency providers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import CredentialEncryptionConfig
from azents.core.deps import get_credential_encryption_config
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

from .service import RuntimeProviderEnrollmentService


def get_runtime_provider_enrollment_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    credential_encryption: Annotated[
        CredentialEncryptionConfig,
        Depends(get_credential_encryption_config),
    ],
) -> RuntimeProviderEnrollmentService:
    """Build the Provider enrollment service for one request."""
    return RuntimeProviderEnrollmentService(
        session_manager=session_manager,
        repository=RuntimeProviderControlRepository(),
        provider_repository=RuntimeProviderRepository(),
        verifier=RuntimeProviderCredentialVerifier(credential_encryption.key),
    )
