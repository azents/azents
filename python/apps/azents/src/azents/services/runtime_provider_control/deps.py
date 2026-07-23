"""Runtime Provider Control dependency providers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.deps import (
    get_appctx,
    get_config,
    get_credential_encryption_config,
)
from azents.core.redis import create_redis_client
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.utils.appctx import AppContext

from .rate_limit import RedisRuntimeProviderEnrollmentRateLimiter
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
        f"{__name__}.get_runtime_provider_enrollment_rate_limiter",
        create,
    )
