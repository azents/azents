"""Runtime Provider enrollment service authority tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from azcommon.datetime import tznow
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProviderBootstrapSourceCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.runtime_provider_bootstrap.data import (
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapSnapshot,
)
from azents.services.runtime_provider_bootstrap.service import (
    RuntimeProviderBootstrapService,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderEnrollmentUnavailable,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)


@asynccontextmanager
async def _session_context(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """Expose one test session through the production SessionManager shape."""
    yield session


def _session_manager(session: AsyncSession) -> SessionManager[AsyncSession]:
    """Build one production-shaped SessionManager."""
    return lambda: _session_context(session)


class TestRuntimeProviderEnrollmentService:
    """Verify bootstrap enrollment authority remains source-bound."""

    async def test_bootstrap_source_can_issue_only_for_owned_declaration(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Another trusted source cannot enroll a Provider it does not own."""
        session_manager = _session_manager(rdb_session)
        provider_repository = RuntimeProviderRepository()
        bootstrap_result = await RuntimeProviderBootstrapService(
            session_manager=session_manager,
            repository=provider_repository,
            system_setting_repository=SystemSettingRepository(),
        ).reconcile(
            RuntimeProviderBootstrapSnapshot(
                source_key="helm/default/azents",
                adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
                source_revision="revision-1",
                source_digest="digest-1",
                declarations=(
                    RuntimeProviderBootstrapDeclarationInput(
                        declaration_key="runtime-provider-kubernetes",
                        provider_logical_id="system-kubernetes",
                        kind=RuntimeProviderKind.KUBERNETES,
                        display_name="Kubernetes",
                        enabled=True,
                        availability_mode=(
                            RuntimeProviderAvailabilityMode.PLATFORM_WIDE
                        ),
                        capabilities={},
                        config_schema=None,
                        metadata=None,
                        creation_seeds=None,
                    ),
                ),
            )
        )
        provider_id = bootstrap_result.created_provider_ids[0]
        other_source = await provider_repository.get_or_create_bootstrap_source(
            rdb_session,
            create=RuntimeProviderBootstrapSourceCreate(
                source_key="helm/other/azents",
                adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
            ),
        )
        service = RuntimeProviderEnrollmentService(
            session_manager=session_manager,
            repository=RuntimeProviderControlRepository(),
            provider_repository=provider_repository,
            verifier=RuntimeProviderCredentialVerifier(Fernet.generate_key().decode()),
        )

        with pytest.raises(
            RuntimeProviderEnrollmentUnavailable,
            match="bootstrap_source_unauthorized",
        ):
            await service.issue_grant(
                provider_id=provider_id,
                expires_at=tznow() + datetime.timedelta(minutes=5),
                issued_by_user_id=None,
                issued_by_source_id=other_source.id,
            )

        issued = await service.issue_grant(
            provider_id=provider_id,
            expires_at=tznow() + datetime.timedelta(minutes=5),
            issued_by_user_id=None,
            issued_by_source_id=bootstrap_result.source_id,
        )
        assert issued.provider_id == provider_id
