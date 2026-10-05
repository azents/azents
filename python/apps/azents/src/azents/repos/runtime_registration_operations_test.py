"""Native PostgreSQL atomic acceptance and completed-operation evidence."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    RuntimeConnectionAuthorityKind,
    RuntimeProviderAuditEventType,
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOwner,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_connection_registration import (
    RuntimeConnectionRegistrationUnavailable,
)
from azents.core.runtime_provider_control import RuntimeProviderCredentialAuthentication
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.core.runtime_provider_data import RuntimeProvider
from azents.rdb.models.runtime_connection_generation import (
    RDBRuntimeConnectionGeneration,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_binding import RDBRuntimeProviderAuthBinding
from azents.rdb.models.runtime_provider_bootstrap import RDBRuntimeProviderAuditEvent
from azents.rdb.models.runtime_provider_control import RDBRuntimeProviderConnection
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_connection_generation.repository import (
    RuntimeConnectionGenerationRepository,
)
from azents.repos.runtime_connection_registration_operations import (
    RuntimeProviderConnectionRegistrationOperationRepository,
)
from azents.repos.runtime_provider.data import (
    RuntimeProviderAuditEventCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBindingCreate
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.operations import (
    RuntimeProviderControlOperationRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeProviderRegistration,
)


class _FailingAuditRepository(RuntimeProviderRepository):
    failure: str

    def __init__(self, failure: str) -> None:
        self.failure = failure

    async def get_by_id(
        self, session: ReadSession, *, provider_id: str
    ) -> RuntimeProvider | None:
        """Inspect native read-only mode in the actual observation scope."""
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        return await super().get_by_id(session, provider_id=provider_id)

    async def append_audit_event(
        self, session: WriteSession, *, create: RuntimeProviderAuditEventCreate
    ) -> None:
        """Fail only after connection and binding writes and audit INSERT executed."""
        await super().append_audit_event(session, create=create)
        if self.failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("forced final acceptance failure")


@pytest.mark.parametrize("failure", ["exception", "cancel"])
async def test_provider_acceptance_rolls_back_every_write_before_success(
    rdb_engine: AsyncEngine, latest_db_schema: None, failure: str
) -> None:
    """Generation acceptance, connection, binding and audit form one atomic group."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    provider_logical_id = f"ownership-{uuid7()}"
    now = tznow()
    providers = RuntimeProviderRepository()
    bindings = RuntimeProviderAuthBindingRepository()
    async with writes() as session:
        provider = await providers.create(
            session,
            RuntimeProviderCreate(
                provider_id=provider_logical_id,
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Atomic registration fixture",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        binding = await bindings.create(
            session,
            create=RuntimeProviderAuthBindingCreate(
                provider_id=provider.id,
                auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                subject="system:serviceaccount:test:provider",
                owner=RuntimeProviderBindingOwner.ADMIN,
                bootstrap_declaration_id=None,
                config=None,
            ),
        )
    authentication = RuntimeProviderCredentialAuthentication(
        binding_id=binding.id,
        credential_id=None,
        provider_id=provider.provider_id,
        provider_resource_id=provider.id,
        provider_kind=provider.kind,
        provider_scope=provider.scope,
        provider_workspace_id=None,
        auth_method=binding.auth_method,
        auth_subject=binding.subject,
        evidence_expires_at=now + datetime.timedelta(minutes=5),
    )
    registration = RuntimeProviderRegistration(
        provider_id=provider.provider_id,
        provider_type="kubernetes",
        scope="system",
        workspace_id=None,
        protocol_version="provider-v1",
        capabilities=RuntimeProtocolCapabilities(("lifecycle",)),
        config_schema_version="v1",
        metadata={},
        capability_contract={},
        operational_diagnostics=None,
        auth_credential_id="workload-credential",
        connection_id=f"connection-{uuid7()}",
        owner_replica_id="control-test",
    )
    control = RuntimeProviderControlOperationRepository(
        session_manager=writes,
        repository=RuntimeProviderControlRepository(),
        provider_repository=_FailingAuditRepository(failure),
        binding_repository=bindings,
        verifier=RuntimeProviderCredentialVerifier(Fernet.generate_key().decode()),
    )
    active_scopes: list[bool] = []

    @asynccontextmanager
    async def tracked_writes() -> AsyncIterator[WriteSession]:
        active_scopes.append(True)
        try:
            async with writes() as session:
                yield session
        finally:
            active_scopes.pop()

    generations = RuntimeConnectionGenerationRepository()
    owner = RuntimeProviderConnectionRegistrationOperationRepository(
        session_manager=tracked_writes,
        read_session_manager=reads,
        generation_repository=generations,
        provider_control=control,
    )
    try:
        generation = await owner.allocate(provider.id)
        assert not active_scopes
        await owner.observe(
            authentication=authentication, generation=generation, validated_at=now
        )
        assert not active_scopes
        async with writes() as concurrent_writer:
            await providers.lock_by_id_for_authority(
                concurrent_writer, provider_id=provider.id
            )
            await bindings.lock_by_id_for_authority(
                concurrent_writer, binding_id=binding.id
            )
            # The deadline guards an accidental blocking lock, not test ordering.
            async with asyncio.timeout(5):
                await owner.observe(
                    authentication=authentication,
                    generation=generation,
                    validated_at=now,
                )
        assert not active_scopes
        rejected = asyncio.CancelledError if failure == "cancel" else RuntimeError
        with pytest.raises(rejected):
            await owner.accept(
                authentication=authentication,
                generation=generation,
                registration=registration,
                authorized_at=now,
                registered_at=now,
            )
        assert not active_scopes
        async with reads() as reader:
            state = await generations.get_generation(
                reader,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=provider.id,
            )
            assert state is not None
            assert state.high_water_generation == generation
            assert state.accepted_generation == 0
            assert (
                await reader.read_session.scalar(
                    sa.select(RDBRuntimeProviderAuthBinding.last_connected_at).where(
                        RDBRuntimeProviderAuthBinding.id == binding.id
                    )
                )
                is None
            )
            assert (
                await reader.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBRuntimeProviderConnection)
                    .where(RDBRuntimeProviderConnection.provider_id == provider.id)
                )
                == 0
            )
            assert (
                await reader.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBRuntimeProviderAuditEvent)
                    .where(
                        RDBRuntimeProviderAuditEvent.provider_id == provider.id,
                        RDBRuntimeProviderAuditEvent.event_type
                        == RuntimeProviderAuditEventType.CONNECTION_OPENED,
                    )
                )
                == 0
            )
        owner = dataclasses.replace(
            owner,
            provider_control=dataclasses.replace(
                control, provider_repository=providers
            ),
        )
        await owner.accept(
            authentication=authentication,
            generation=generation,
            registration=registration,
            authorized_at=now,
            registered_at=now,
        )
        assert not active_scopes
        async with reads() as reader:
            state = await generations.get_generation(
                reader,
                connection_kind=RuntimeConnectionAuthorityKind.PROVIDER,
                subject_id=provider.id,
            )
            assert state is not None and state.accepted_generation == generation
            assert (
                await reader.read_session.scalar(
                    sa.select(RDBRuntimeProviderAuthBinding.last_connected_at).where(
                        RDBRuntimeProviderAuthBinding.id == binding.id
                    )
                )
                == now
            )
            assert (
                await reader.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBRuntimeProviderConnection)
                    .where(RDBRuntimeProviderConnection.provider_id == provider.id)
                )
                == 1
            )
        newer = await owner.allocate(provider.id)
        assert newer == generation + 1
        with pytest.raises(RuntimeConnectionRegistrationUnavailable):
            await owner.accept(
                authentication=authentication,
                generation=generation,
                registration=registration,
                authorized_at=now,
                registered_at=now,
            )
    finally:
        async with writes() as session:
            for model in (
                RDBRuntimeProviderConnection,
                RDBRuntimeProviderAuditEvent,
                RDBRuntimeProviderAuthBinding,
            ):
                await session.write_session.execute(
                    sa.delete(model).where(model.provider_id == provider.id)
                )
            await session.write_session.execute(
                sa.delete(RDBRuntimeConnectionGeneration).where(
                    RDBRuntimeConnectionGeneration.connection_kind
                    == RuntimeConnectionAuthorityKind.PROVIDER,
                    RDBRuntimeConnectionGeneration.subject_id == provider.id,
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id == provider.id
                )
            )
