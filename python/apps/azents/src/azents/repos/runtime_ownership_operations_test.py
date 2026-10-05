"""Real PostgreSQL commit/rollback/read-only evidence for Runtime operation owners."""

import datetime
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOwner,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationReconcileTask
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_binding import RDBRuntimeProviderAuthBinding
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderBootstrapSource,
)
from azents.rdb.models.runtime_provider_control import (
    RDBRuntimeProviderCredential,
    RDBRuntimeProviderEnrollmentGrant,
)
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_profile_reconciliation_operations import (
    RuntimeProfileReconciliationOperationRepository,
)
from azents.repos.runtime_profile_resolution_operations import (
    RuntimeProfileResolutionOperationRepository,
)
from azents.repos.runtime_provider.data import (
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_auth_operations import (
    RuntimeProviderAuthenticationOperationRepository,
    RuntimeProviderAuthenticationRejected,
)
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBindingCreate
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.data import (
    RuntimeProviderCredentialCreate,
    RuntimeProviderEnrollmentGrantCreate,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.runtime_terminal_authority_read import (
    RuntimeTerminalAuthorityReadRepository,
)
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import User
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


class _AuthenticationFixture(NamedTuple):
    provider_id: str
    source_id: str
    binding_id: str
    grant_id: str
    credential_id: str


async def _seed_authentication(session: WriteSession) -> _AuthenticationFixture:
    """Commit-ready aggregate without external enrollment or provider work."""
    providers = RuntimeProviderRepository()
    provider = await providers.create(
        session,
        RuntimeProviderCreate(
            provider_id=f"ownership-{uuid7()}",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.DOCKER,
            display_name="Ownership authentication fixture",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    source = await providers.get_or_create_bootstrap_source(
        session,
        create=RuntimeProviderBootstrapSourceCreate(
            source_key=f"ownership-{uuid7().hex}",
            adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
        ),
    )
    binding = await RuntimeProviderAuthBindingRepository().create(
        session,
        create=RuntimeProviderAuthBindingCreate(
            provider_id=provider.id,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject=f"admin:{provider.id}",
            owner=RuntimeProviderBindingOwner.ADMIN,
            bootstrap_declaration_id=None,
            config=None,
        ),
    )
    control = RuntimeProviderControlRepository()
    now = tznow()
    grant = await control.create_enrollment_grant(
        session,
        create=RuntimeProviderEnrollmentGrantCreate(
            provider_id=provider.id,
            binding_id=binding.id,
            verifier=f"grant-{uuid7()}",
            expires_at=now + datetime.timedelta(minutes=5),
            issued_by_user_id=None,
            issued_by_source_id=source.id,
        ),
    )
    credential = await control.create_credential_and_consume_grant(
        session,
        grant_id=grant.id,
        credential=RuntimeProviderCredentialCreate(
            provider_id=provider.id,
            binding_id=binding.id,
            verifier="known-verifier",
            expires_at=None,
            issued_grant_id=grant.id,
        ),
        consumed_at=now,
    )
    assert credential is not None
    return _AuthenticationFixture(
        provider.id, source.id, binding.id, grant.id, credential.id
    )


class _RejectAuthenticationBindingRepository(RuntimeProviderAuthBindingRepository):
    async def mark_authenticated(
        self,
        session: WriteSession,
        *,
        binding_id: str,
        authenticated_at: datetime.datetime,
    ) -> bool:
        """Force rejection after the earlier credential usage UPDATE executed."""
        return False


async def test_authentication_owner_commits_or_rolls_back_both_writes(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """An independent read observes neither partial usage nor half-authentication."""
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    async with writes() as session:
        fixture = await _seed_authentication(session)
    owner = RuntimeProviderAuthenticationOperationRepository(
        session_manager=writes,
        repository=RuntimeProviderControlRepository(),
        provider_repository=RuntimeProviderRepository(),
        binding_repository=_RejectAuthenticationBindingRepository(),
    )
    now = tznow()
    try:
        with pytest.raises(RuntimeProviderAuthenticationRejected) as failure:
            await owner.verify_issued_token(verifier="known-verifier", now=now)
        assert failure.value.code == "binding_unavailable"
        async with reads() as reader:
            used = await reader.read_session.scalar(
                sa.select(RDBRuntimeProviderCredential.last_used_at).where(
                    RDBRuntimeProviderCredential.id == fixture.credential_id
                )
            )
            authenticated = await reader.read_session.scalar(
                sa.select(RDBRuntimeProviderAuthBinding.last_authenticated_at).where(
                    RDBRuntimeProviderAuthBinding.id == fixture.binding_id
                )
            )
            assert used is None
            assert authenticated is None
        owner.binding_repository = RuntimeProviderAuthBindingRepository()
        record = await owner.verify_issued_token(verifier="known-verifier", now=now)
        assert record.credential_id == fixture.credential_id
        async with reads() as reader:
            used = await reader.read_session.scalar(
                sa.select(RDBRuntimeProviderCredential.last_used_at).where(
                    RDBRuntimeProviderCredential.id == fixture.credential_id
                )
            )
            authenticated = await reader.read_session.scalar(
                sa.select(RDBRuntimeProviderAuthBinding.last_authenticated_at).where(
                    RDBRuntimeProviderAuthBinding.id == fixture.binding_id
                )
            )
            assert used == now
            assert authenticated == now
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderCredential).where(
                    RDBRuntimeProviderCredential.id == fixture.credential_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderEnrollmentGrant).where(
                    RDBRuntimeProviderEnrollmentGrant.id == fixture.grant_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderAuthBinding).where(
                    RDBRuntimeProviderAuthBinding.id == fixture.binding_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id == fixture.provider_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderBootstrapSource).where(
                    RDBRuntimeProviderBootstrapSource.id == fixture.source_id
                )
            )


async def test_completed_reconciliation_owner_preserves_reclaimed_attempt_fence(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Old attempt completion cannot overwrite the independently committed reclaim."""
    writes = create_read_write_session_manager(rdb_engine)
    profiles = RuntimeProfileRepository()
    source_id = uuid7().hex
    now = tznow()
    async with writes() as session:
        task = await profiles.enqueue_reconcile_task(
            session,
            source_type=RuntimeReconcileSourceKind.PROVIDER_CAPABILITY,
            source_id=source_id,
            source_version="one",
            available_at=now,
        )
    owner = RuntimeProfileReconciliationOperationRepository(
        session_manager=writes,
        profile_repository=profiles,
        resolution_operations=RuntimeProfileResolutionOperationRepository(
            session_manager=writes,
            agent_repository=AgentRepository(),
            runtime_repository=AgentRuntimeRepository(),
            profile_repository=profiles,
            provider_repository=RuntimeProviderRepository(),
            provider_policy_repository=RuntimeProviderPolicyRepository(),
        ),
    )
    try:
        first = await owner.claim(
            now=now, reclaim_before=now - datetime.timedelta(minutes=5), limit=1
        )
        assert first[0].id == task.id
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBRuntimeConfigurationReconcileTask)
                .where(RDBRuntimeConfigurationReconcileTask.id == task.id)
                .values(updated_at=now - datetime.timedelta(minutes=10))
            )
        second = await owner.claim(
            now=now, reclaim_before=now - datetime.timedelta(minutes=5), limit=1
        )
        assert second[0].attempt == first[0].attempt + 1
        assert not await owner.finalize(
            first[0], cursor="stale-agent", has_more=False, available_at=now
        )
        assert await owner.finalize(
            second[0], cursor="current-agent", has_more=False, available_at=now
        )
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBRuntimeConfigurationReconcileTask).where(
                    RDBRuntimeConfigurationReconcileTask.id == task.id
                )
            )


class _ReadOnlyEvidenceUserRepository(UserRepository):
    observed: bool = False

    async def get(self, session: ReadSession, user_id: str) -> User | None:
        """Observe native PostgreSQL mode inside the actual authority read operation."""
        assert (
            await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            == "on"
        )
        self.observed = True
        return await super().get(session, user_id)


async def test_terminal_authority_owner_uses_native_read_only_scope(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """The detached fail-closed snapshot returns after PostgreSQL RO scope exits."""
    users = _ReadOnlyEvidenceUserRepository()
    owner = RuntimeTerminalAuthorityReadRepository(
        session_manager=create_read_only_session_manager(rdb_engine),
        user_repository=users,
        authentication_session_repository=SessionRepository(),
        workspace_repository=WorkspaceRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        agent_repository=AgentRepository(),
        agent_admin_repository=AgentAdminRepository(),
        agent_session_repository=AgentSessionRepository(),
        runtime_repository=AgentRuntimeRepository(),
        profile_repository=RuntimeProfileRepository(),
    )
    snapshot = await owner.read_snapshot(
        user_id=uuid7().hex,
        authentication_session_id=uuid7().hex,
        workspace_handle="missing-workspace",
        agent_id=uuid7().hex,
        session_id=uuid7().hex,
        resolved_at=tznow(),
    )
    assert users.observed
    assert snapshot.reason_code == "access_denied"
    assert snapshot.runtime is None
