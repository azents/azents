"""Runtime Provider Control dependency providers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.deps import get_appctx, get_config, get_credential_encryption_config
from azents.core.redis import create_redis_client
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_auth_operations import (
    RuntimeProviderAuthenticationOperationRepository,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.operations import (
    RuntimeProviderControlOperationRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.services.runtime_provider_control.provider_auth import (
    IssuedTokenProviderAuthVerifier,
    KubernetesServiceAccountProviderAuthVerifier,
    KubernetesServiceAccountTokenReviewer,
    ProviderAuthRegistry,
    ProviderAuthVerifier,
)
from azents.utils.appctx import AppContext

from .rate_limit import RedisRuntimeProviderEnrollmentRateLimiter
from .service import RuntimeProviderEnrollmentService


def get_runtime_provider_enrollment_service(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    credential_encryption: Annotated[
        CredentialEncryptionConfig, Depends(get_credential_encryption_config)
    ],
) -> RuntimeProviderEnrollmentService:
    """Build the Provider enrollment service for one request."""
    return create_runtime_provider_enrollment_service(
        session_manager=session_manager,
        repository=RuntimeProviderControlRepository(),
        provider_repository=RuntimeProviderRepository(),
        binding_repository=RuntimeProviderAuthBindingRepository(),
        verifier=RuntimeProviderCredentialVerifier(credential_encryption.key),
        kubernetes_token_reviewer=None,
        auth_registry=None,
    )


async def get_runtime_provider_enrollment_rate_limiter(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    config: Annotated[Config, Depends(get_config)],
) -> RedisRuntimeProviderEnrollmentRateLimiter:
    """Return the process-wide public enrollment exchange rate limiter."""

    async def create() -> AsyncIterator[RedisRuntimeProviderEnrollmentRateLimiter]:
        redis = create_redis_client(config.redis.url)
        try:
            yield RedisRuntimeProviderEnrollmentRateLimiter(redis)
        finally:
            await redis.aclose()

    return await appctx.get_variable(
        f"{__name__}.get_runtime_provider_enrollment_rate_limiter", create
    )


def create_runtime_provider_enrollment_service(
    *,
    session_manager: SessionManager[WriteSession],
    repository: RuntimeProviderControlRepository,
    provider_repository: RuntimeProviderRepository,
    binding_repository: RuntimeProviderAuthBindingRepository,
    verifier: RuntimeProviderCredentialVerifier,
    kubernetes_token_reviewer: KubernetesServiceAccountTokenReviewer | None,
    auth_registry: ProviderAuthRegistry | None,
) -> RuntimeProviderEnrollmentService:
    """Compose completed enrollment operations and independent authentication."""
    operations = RuntimeProviderControlOperationRepository(
        session_manager=session_manager,
        repository=repository,
        provider_repository=provider_repository,
        binding_repository=binding_repository,
        verifier=verifier,
    )
    if auth_registry is None:
        authentication_operations = RuntimeProviderAuthenticationOperationRepository(
            session_manager=session_manager,
            repository=repository,
            provider_repository=provider_repository,
            binding_repository=binding_repository,
        )
        verifiers: list[ProviderAuthVerifier] = [
            IssuedTokenProviderAuthVerifier(
                operations=authentication_operations, credential_verifier=verifier
            )
        ]
        if kubernetes_token_reviewer is not None:
            verifiers.append(
                KubernetesServiceAccountProviderAuthVerifier(
                    operations=authentication_operations,
                    token_reviewer=kubernetes_token_reviewer,
                )
            )
        auth_registry = ProviderAuthRegistry(tuple(verifiers))
    return RuntimeProviderEnrollmentService(
        operations=operations, auth_registry=auth_registry, verifier=verifier
    )
