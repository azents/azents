"""Provider registration observations are independent from final acceptance."""

import asyncio
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_binding import RDBRuntimeProviderAuthBinding
from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_profile.repository_test import _create_provider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBindingCreate
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)


@pytest.mark.asyncio
async def test_provider_observation_nonblocking_but_revoked_binding_cannot_publish(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Held Provider/binding writers permit observations, not stale final acceptance."""
    reads = create_read_only_session_manager(rdb_engine)
    writes = create_read_write_session_manager(rdb_engine)
    now = datetime.datetime.now(datetime.UTC)
    providers = RuntimeProviderRepository()
    bindings = RuntimeProviderAuthBindingRepository()
    provider_id: str | None = None
    binding_id: str | None = None
    writer: asyncio.Task[None] | None = None
    held, release = asyncio.Event(), asyncio.Event()
    try:
        async with writes() as session:
            provider_id = await _create_provider(
                session, logical_id=f"provider-observer-{uuid4().hex}"
            )
            provider = await providers.get_by_id(session, provider_id=provider_id)
            assert provider is not None
            binding = await bindings.create(
                session,
                create=RuntimeProviderAuthBindingCreate(
                    provider_id=provider_id,
                    auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                    subject=f"system:serviceaccount:test:{uuid4().hex}",
                    owner=RuntimeProviderBindingOwner.ADMIN,
                    bootstrap_declaration_id=None,
                    config=None,
                ),
            )
            binding_id = binding.id
        authentication = RuntimeProviderCredentialAuthentication(
            binding_id=binding.id,
            credential_id=None,
            provider_id=provider.provider_id,
            provider_resource_id=provider.id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
            auth_method=binding.auth_method,
            auth_subject=binding.subject,
            evidence_expires_at=now + datetime.timedelta(minutes=5),
        )
        service = RuntimeProviderEnrollmentService(
            session_manager=writes,
            repository=RuntimeProviderControlRepository(),
            provider_repository=providers,
            binding_repository=bindings,
            verifier=RuntimeProviderCredentialVerifier(Fernet.generate_key().decode()),
            kubernetes_token_reviewer=None,
            auth_registry=None,
        )

        async def hold() -> None:
            async with writes() as session:
                await session.write_session.execute(
                    sa.select(RDBRuntimeProvider.id)
                    .where(RDBRuntimeProvider.id == provider.id)
                    .with_for_update()
                )
                await session.write_session.execute(
                    sa.select(RDBRuntimeProviderAuthBinding.id)
                    .where(RDBRuntimeProviderAuthBinding.id == binding.id)
                    .with_for_update()
                )
                held.set()
                await release.wait()

        writer = asyncio.create_task(hold())
        await asyncio.wait_for(held.wait(), timeout=5)

        async def observe() -> None:
            async with reads() as session:
                await service.validate_connection_authority_in_transaction(
                    session, authentication=authentication, validated_at=now
                )

        await asyncio.wait_for(observe(), timeout=5)
        assert not release.is_set()
        release.set()
        await writer
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBRuntimeProviderAuthBinding)
                .where(RDBRuntimeProviderAuthBinding.id == binding.id)
                .values(state=RuntimeProviderBindingState.REVOKED)
            )
        with pytest.raises(
            RuntimeProviderCredentialUnavailable, match="binding_unavailable"
        ):
            async with writes() as session:
                await service.create_connection_in_transaction(
                    session,
                    authentication=authentication,
                    connection_id=uuid4().hex,
                    generation=1,
                    reported_provider_type="kubernetes",
                    reported_protocol_version="v3",
                    operational_diagnostics=None,
                    authorized_at=now,
                    connected_at=now,
                )
    finally:
        release.set()
        try:
            if writer is not None:
                await writer
        finally:
            async with writes() as session:
                if binding_id is not None:
                    await session.write_session.execute(
                        sa.delete(RDBRuntimeProviderAuthBinding).where(
                            RDBRuntimeProviderAuthBinding.id == binding_id
                        )
                    )
                if provider_id is not None:
                    await session.write_session.execute(
                        sa.delete(RDBRuntimeProvider).where(
                            RDBRuntimeProvider.id == provider_id
                        )
                    )
