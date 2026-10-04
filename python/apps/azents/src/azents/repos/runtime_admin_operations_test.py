"""Native read-only scopes and atomic Runtime Admin operation regression tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    DockerContainerProfileSpecV1,
    DockerContainerResources,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
)
from azents.core.runtime_provider_bootstrap import (
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapReconcileResult,
    RuntimeProviderBootstrapSnapshot,
)
from azents.rdb.models.runtime_profile import (
    RDBRuntimeConfigurationReconcileTask,
    RDBRuntimeInfrastructureProfile,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_binding import (
    RDBRuntimeProviderAuthBinding,
    RDBRuntimeProviderAuthBindingAuditEvent,
)
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderBootstrapDeclaration,
    RDBRuntimeProviderBootstrapSource,
)
from azents.rdb.models.runtime_provider_control import RDBRuntimeProviderEnrollmentGrant
from azents.rdb.models.user import RDBUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_profile.admin_operations import (
    RuntimeProfileAdminOperationsRepository,
)
from azents.repos.runtime_profile.data import RuntimeConfigurationReconcileTask
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.bootstrap_enrollment_read import (
    BootstrapEnrollmentTarget,
    RuntimeProviderBootstrapEnrollmentReadRepository,
)
from azents.repos.runtime_provider.data import (
    RuntimeProviderBootstrapDeclarationCreate,
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.admin_operations import (
    RuntimeProviderBindingAdminOperationsRepository,
)
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingAuditEvent,
    RuntimeProviderAuthBindingAuditEventCreate,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.services.runtime_profile_admin.service import RuntimeProfileAdminService
from azents.services.runtime_provider_bootstrap.enrollment import (
    RuntimeProviderBootstrapEnrollmentService,
)
from azents.services.runtime_provider_bootstrap.service import (
    RuntimeProviderBootstrapService,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialIssued,
    RuntimeProviderCredentialUnavailable,
    RuntimeProviderEnrollmentGrantIssued,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)
from azents.services.terminal_policy.invalidation_contracts import (
    TerminalPolicySourceInvalidation,
)


@dataclasses.dataclass(frozen=True)
class _AdminRows:
    provider_id: str
    logical_id: str
    source_id: str
    declaration_id: str
    user_id: str


@pytest_asyncio.fixture
async def admin_rows(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_AdminRows]:
    """Commit isolated Provider/source/user evidence for independent readers."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeProviderRepository()
    logical_id = f"admin-ops-{uuid4().hex}"
    async with writes() as session:
        user = await UserRepository().create(
            session, UserCreate(email=f"{uuid4().hex}@example.com")
        )
        provider = await repository.create(
            session,
            RuntimeProviderCreate(
                provider_id=logical_id,
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.DOCKER,
                display_name=logical_id,
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        source = await repository.get_or_create_bootstrap_source(
            session,
            create=RuntimeProviderBootstrapSourceCreate(
                source_key=uuid4().hex,
                adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
            ),
        )
        declaration = await repository.create_bootstrap_declaration(
            session,
            create=RuntimeProviderBootstrapDeclarationCreate(
                source_id=source.id,
                declaration_key="fixture",
                provider_logical_id=logical_id,
                kind=RuntimeProviderKind.DOCKER,
                provider_id=provider.id,
                source_revision="1",
                source_digest="a" * 64,
                state=RuntimeProviderBootstrapDeclarationState.PRESENT,
                creation_seeds=None,
                conflict_code=None,
                conflict_message=None,
                last_seen_at=None,
                withdrawn_at=None,
            ),
        )
        rows = _AdminRows(provider.id, logical_id, source.id, declaration.id, user.id)
    try:
        yield rows
    finally:
        async with writes() as session:
            binding_ids = sa.select(RDBRuntimeProviderAuthBinding.id).where(
                RDBRuntimeProviderAuthBinding.provider_id == rows.provider_id
            )
            profile_ids = sa.select(RDBRuntimeInfrastructureProfile.id).where(
                RDBRuntimeInfrastructureProfile.provider_id == rows.provider_id
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderAuthBindingAuditEvent).where(
                    RDBRuntimeProviderAuthBindingAuditEvent.binding_id.in_(binding_ids)
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderEnrollmentGrant).where(
                    RDBRuntimeProviderEnrollmentGrant.provider_id == rows.provider_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderAuthBinding).where(
                    RDBRuntimeProviderAuthBinding.provider_id == rows.provider_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeConfigurationReconcileTask).where(
                    RDBRuntimeConfigurationReconcileTask.source_id.in_(profile_ids)
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeInfrastructureProfile).where(
                    RDBRuntimeInfrastructureProfile.provider_id == rows.provider_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderBootstrapDeclaration).where(
                    RDBRuntimeProviderBootstrapDeclaration.id == rows.declaration_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProviderBootstrapSource).where(
                    RDBRuntimeProviderBootstrapSource.id == rows.source_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBRuntimeProvider).where(
                    RDBRuntimeProvider.id == rows.provider_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(RDBUser.id == rows.user_id)
            )


def _read_manager(
    engine: AsyncEngine, opened: list[AsyncSession]
) -> SessionManager[ReadSession]:
    """Observe DB-enforced read-only scopes and their actual completion."""
    reads = create_read_only_session_manager(engine)

    @asynccontextmanager
    async def manager() -> AsyncIterator[ReadSession]:
        async with reads() as session:
            opened.append(session.read_session)
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            yield session

    return manager


def _profile_operations(
    engine: AsyncEngine, opened: list[AsyncSession]
) -> RuntimeProfileAdminOperationsRepository:
    return RuntimeProfileAdminOperationsRepository(
        session_manager=create_read_write_session_manager(engine),
        read_session_manager=_read_manager(engine, opened),
        profile_repository=RuntimeProfileRepository(),
        provider_repository=RuntimeProviderRepository(),
        policy_repository=RuntimeProviderPolicyRepository(),
        workspace_repository=WorkspaceRepository(),
    )


def _binding_operations(
    engine: AsyncEngine, opened: list[AsyncSession]
) -> RuntimeProviderBindingAdminOperationsRepository:
    return RuntimeProviderBindingAdminOperationsRepository(
        session_manager=create_read_write_session_manager(engine),
        read_session_manager=_read_manager(engine, opened),
        provider_repository=RuntimeProviderRepository(),
        binding_repository=RuntimeProviderAuthBindingRepository(),
        control_repository=RuntimeProviderControlRepository(),
    )


def _spec() -> DockerContainerProfileSpecV1:
    return DockerContainerProfileSpecV1(
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        contract_family="docker.container-profile",
        schema_version=1,
        runner_resources=DockerContainerResources(
            cpu_reservation_millicores=None,
            cpu_limit_millicores=None,
            memory_reservation_bytes=None,
            memory_limit_bytes=None,
        ),
        network_name=None,
    )


async def test_runtime_admin_reads_finish_while_writer_holds_rows(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows
) -> None:
    """Profile, binding and bootstrap reads tolerate committed descriptive lag."""
    opened: list[AsyncSession] = []
    profiles = _profile_operations(rdb_engine, opened)
    bindings = _binding_operations(rdb_engine, opened)
    profile = await profiles.create_profile(
        admin_rows.logical_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        display_name="read profile",
        description="read profile",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        spec=_spec(),
        terminal_enabled=True,
        actor_user_id=admin_rows.user_id,
    )
    binding = await bindings.create_binding(
        admin_rows.logical_id,
        auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        subject="read binding",
        config=None,
        actor_user_id=admin_rows.user_id,
    )
    bootstrap = RuntimeProviderBootstrapEnrollmentReadRepository(
        session_manager=_read_manager(rdb_engine, opened),
        provider_repository=RuntimeProviderRepository(),
    )
    writes = create_read_write_session_manager(rdb_engine)
    locked = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with writes() as session:
            await session.write_session.execute(
                sa.select(RDBRuntimeProvider.id)
                .where(RDBRuntimeProvider.id == admin_rows.provider_id)
                .with_for_update()
            )
            await session.write_session.execute(
                sa.select(RDBRuntimeInfrastructureProfile.id)
                .where(RDBRuntimeInfrastructureProfile.id == profile.profile.id)
                .with_for_update()
            )
            await session.write_session.execute(
                sa.select(RDBRuntimeProviderAuthBinding.id)
                .where(RDBRuntimeProviderAuthBinding.id == binding.binding.id)
                .with_for_update()
            )
            await session.write_session.execute(
                sa.select(RDBRuntimeProviderBootstrapDeclaration.id)
                .where(
                    RDBRuntimeProviderBootstrapDeclaration.id
                    == admin_rows.declaration_id
                )
                .with_for_update()
            )
            locked.set()
            await release.wait()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)

        async def inspect() -> None:
            assert (
                await profiles.get_profile(
                    admin_rows.logical_id,
                    profile.profile.id,
                    profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
                )
            ).profile.id == profile.profile.id
            assert (
                len(
                    await profiles.list_profiles(
                        admin_rows.logical_id,
                        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
                        include_disabled=False,
                    )
                )
                == 1
            )
            assert (
                await profiles.get_profile_deletion_impact(
                    admin_rows.logical_id,
                    profile.profile.id,
                    profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
                    offset=0,
                    limit=50,
                )
            ).impact.blocking_reference_count == 0
            assert (
                await bindings.get_binding(binding.binding.id)
            ).binding.id == binding.binding.id
            assert len(await bindings.list_bindings(admin_rows.logical_id)) == 1
            assert (
                len(
                    await bindings.list_audit_events(
                        binding.binding.id, offset=0, limit=50
                    )
                )
                == 1
            )
            assert await bootstrap.resolve(
                provider_logical_id=admin_rows.logical_id,
                source_id=admin_rows.source_id,
            ) == BootstrapEnrollmentTarget(admin_rows.provider_id, admin_rows.source_id)

        await asyncio.wait_for(inspect(), timeout=5)
        assert len(opened) == 7 and all(
            not session.in_transaction() for session in opened
        )
        assert not release.is_set()
    finally:
        release.set()
        await task


@pytest.mark.parametrize(
    "denial", ["missing-provider", "wrong-source", "absent", "conflict"]
)
async def test_bootstrap_target_requires_exact_present_source(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows, denial: str
) -> None:
    """Retain exact Provider/declaration/source matching without adding admission."""
    if denial in {"absent", "conflict"}:
        async with create_read_write_session_manager(rdb_engine)() as session:
            await session.write_session.execute(
                sa.update(RDBRuntimeProviderBootstrapDeclaration)
                .where(
                    RDBRuntimeProviderBootstrapDeclaration.id
                    == admin_rows.declaration_id
                )
                .values(state=RuntimeProviderBootstrapDeclarationState(denial))
            )
    opened: list[AsyncSession] = []
    operation = RuntimeProviderBootstrapEnrollmentReadRepository(
        session_manager=_read_manager(rdb_engine, opened),
        provider_repository=RuntimeProviderRepository(),
    )
    message = (
        "Bootstrap Provider was not created"
        if denial == "missing-provider"
        else "Bootstrap source does not own"
    )
    with pytest.raises(RuntimeError, match=message):
        await operation.resolve(
            provider_logical_id="missing"
            if denial == "missing-provider"
            else admin_rows.logical_id,
            source_id=uuid4().hex if denial == "wrong-source" else admin_rows.source_id,
        )
    assert len(opened) == 1 and not opened[0].in_transaction()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_rotation_rolls_back_version_grant_and_audit_on_failure(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows, error_type: type[BaseException]
) -> None:
    """An audit failure cancels every mutation, not only the final audit append."""
    operation = _binding_operations(rdb_engine, [])
    binding = await operation.create_binding(
        admin_rows.logical_id,
        auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        subject="rollback binding",
        config=None,
        actor_user_id=admin_rows.user_id,
    )

    class FailingAudit(RuntimeProviderAuthBindingRepository):
        async def append_audit_event(
            self,
            session: WriteSession,
            *,
            create: RuntimeProviderAuthBindingAuditEventCreate,
        ) -> RuntimeProviderAuthBindingAuditEvent:
            raise error_type("audit interrupted")

    operation.binding_repository = FailingAudit()
    now = datetime.datetime.now(datetime.UTC)
    with pytest.raises(error_type, match="audit interrupted"):
        await operation.rotate_binding(
            binding.binding.id,
            expected_admin_version=binding.binding.admin_version,
            expires_at=now + datetime.timedelta(minutes=5),
            actor_user_id=admin_rows.user_id,
            grant_verifier="test-verifier",
            now=now,
        )
    async with create_read_only_session_manager(rdb_engine)() as session:
        current = await RuntimeProviderAuthBindingRepository().get_by_id(
            session, binding_id=binding.binding.id
        )
        assert (
            current is not None
            and current.admin_version == binding.binding.admin_version
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBRuntimeProviderEnrollmentGrant)
                .where(
                    RDBRuntimeProviderEnrollmentGrant.binding_id == binding.binding.id
                )
            )
            == 0
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBRuntimeProviderAuthBindingAuditEvent)
                .where(
                    RDBRuntimeProviderAuthBindingAuditEvent.binding_id
                    == binding.binding.id
                )
            )
            == 1
        )


async def test_terminal_only_replace_invalidates_after_commit_without_reconcile(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows
) -> None:
    """A terminal-only change commits before external publication and no task add."""
    operation = _profile_operations(rdb_engine, [])
    profile = await operation.create_profile(
        admin_rows.logical_id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        display_name="terminal profile",
        description="terminal profile",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        spec=_spec(),
        terminal_enabled=True,
        actor_user_id=admin_rows.user_id,
    )
    observed: list[TerminalPolicySourceInvalidation] = []

    class Publisher:
        async def publish_terminal_policy_invalidation(
            self, invalidation: TerminalPolicySourceInvalidation
        ) -> None:
            async with create_read_only_session_manager(rdb_engine)() as session:
                current = await RuntimeProfileRepository().get_infrastructure_profile(
                    session, profile_id=profile.profile.id
                )
                assert current is not None and not current.terminal_enabled
                assert current.version == profile.profile.version + 1
                assert (
                    await session.read_session.scalar(
                        sa.select(sa.func.count())
                        .select_from(RDBRuntimeConfigurationReconcileTask)
                        .where(
                            RDBRuntimeConfigurationReconcileTask.source_id == current.id
                        )
                    )
                    == 1
                )
            observed.append(invalidation)

    service = RuntimeProfileAdminService(
        repository=operation, terminal_policy_invalidation_publisher=Publisher()
    )
    result = await service.replace_profile(
        admin_rows.logical_id,
        profile.profile.id,
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        expected_version=profile.profile.version,
        display_name=profile.profile.display_name,
        description=profile.profile.description,
        lifecycle=profile.profile.lifecycle,
        spec=_spec(),
        terminal_enabled=False,
        actor_user_id=admin_rows.user_id,
    )
    assert result.profile.version == profile.profile.version + 1
    assert len(observed) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_profile_create_rolls_back_profile_when_enqueue_fails(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows, error_type: type[BaseException]
) -> None:
    """Profile creation and source reconcile enqueue are one mutation group."""
    operation = _profile_operations(rdb_engine, [])

    class FailingEnqueue(RuntimeProfileRepository):
        async def enqueue_reconcile_task(
            self,
            session: WriteSession,
            *,
            source_type: RuntimeReconcileSourceKind,
            source_id: str,
            source_version: str,
            available_at: datetime.datetime,
        ) -> RuntimeConfigurationReconcileTask:
            raise error_type("enqueue interrupted")

    operation.profile_repository = FailingEnqueue()
    with pytest.raises(error_type, match="enqueue interrupted"):
        await operation.create_profile(
            admin_rows.logical_id,
            profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
            display_name="rollback profile",
            description="rollback profile",
            lifecycle=RuntimeProfileLifecycle.ACTIVE,
            spec=_spec(),
            terminal_enabled=True,
            actor_user_id=admin_rows.user_id,
        )
    async with create_read_only_session_manager(rdb_engine)() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBRuntimeInfrastructureProfile)
                .where(
                    RDBRuntimeInfrastructureProfile.provider_id
                    == admin_rows.provider_id
                )
            )
            == 0
        )


@pytest.mark.parametrize(
    "existing", ["matching", "wrong-provider", "invalid", "missing"]
)
async def test_bootstrap_credential_io_follows_completed_target_read(
    rdb_engine: AsyncEngine, admin_rows: _AdminRows, existing: str
) -> None:
    """Credential reuse or issuance starts only after the ownership read closes."""
    opened: list[AsyncSession] = []
    repository = RuntimeProviderBootstrapEnrollmentReadRepository(
        session_manager=_read_manager(rdb_engine, opened),
        provider_repository=RuntimeProviderRepository(),
    )
    bootstrap = Mock(spec=RuntimeProviderBootstrapService)
    bootstrap.reconcile = AsyncMock(
        return_value=RuntimeProviderBootstrapReconcileResult(
            source_id=admin_rows.source_id,
            created_provider_ids=(),
            reconciled_provider_ids=(admin_rows.provider_id,),
            withdrawn_provider_ids=(),
            conflicted_declaration_keys=(),
        )
    )
    enrollment = Mock(spec=RuntimeProviderEnrollmentService)

    def assert_closed() -> None:
        assert len(opened) == 1 and not opened[0].in_transaction()

    async def authenticate(*, secret: str) -> RuntimeProviderCredentialAuthentication:
        assert_closed()
        assert secret == "existing-secret"
        if existing == "invalid":
            raise RuntimeProviderCredentialUnavailable("credential_invalid")
        return RuntimeProviderCredentialAuthentication(
            binding_id="binding",
            credential_id="credential",
            provider_id=admin_rows.logical_id,
            provider_resource_id=(
                uuid4().hex if existing == "wrong-provider" else admin_rows.provider_id
            ),
            provider_kind=RuntimeProviderKind.DOCKER,
            provider_scope=RuntimeProviderScope.SYSTEM,
            provider_workspace_id=None,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject="fixture",
            evidence_expires_at=None,
        )

    async def issue(
        *,
        provider_id: str,
        expires_at: datetime.datetime,
        issued_by_user_id: str | None,
        issued_by_source_id: str | None,
    ) -> RuntimeProviderEnrollmentGrantIssued:
        assert_closed()
        assert provider_id == admin_rows.provider_id
        assert issued_by_user_id is None
        assert issued_by_source_id == admin_rows.source_id
        return RuntimeProviderEnrollmentGrantIssued(
            grant_id="grant",
            provider_id=provider_id,
            secret="grant-secret",
            expires_at=expires_at,
        )

    async def exchange(
        *,
        grant_id: str,
        secret: str,
        credential_expires_at: datetime.datetime | None,
        source_address: str | None,
    ) -> RuntimeProviderCredentialIssued:
        assert_closed()
        assert grant_id == "grant" and secret == "grant-secret"
        assert credential_expires_at is None and source_address is None
        return RuntimeProviderCredentialIssued(
            credential_id="credential",
            provider_id=admin_rows.provider_id,
            secret="new-secret",
            expires_at=None,
        )

    enrollment.authenticate_credential = AsyncMock(side_effect=authenticate)
    enrollment.issue_grant = AsyncMock(side_effect=issue)
    enrollment.exchange_grant = AsyncMock(side_effect=exchange)
    service = RuntimeProviderBootstrapEnrollmentService(
        repository=repository,
        bootstrap_service=bootstrap,
        enrollment_service=enrollment,
    )
    snapshot = RuntimeProviderBootstrapSnapshot(
        source_key="fixture",
        adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
        source_revision="1",
        source_digest="a" * 64,
        declarations=(
            RuntimeProviderBootstrapDeclarationInput(
                declaration_key="fixture",
                provider_logical_id=admin_rows.logical_id,
                kind=RuntimeProviderKind.DOCKER,
                display_name="fixture",
                enabled=True,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
                creation_seeds=None,
            ),
        ),
    )
    result = await service.ensure_credential(
        snapshot=snapshot,
        provider_logical_id=admin_rows.logical_id,
        existing_secret=None if existing == "missing" else "existing-secret",
    )
    assert result.changed == (existing != "matching")
    assert result.secret == (
        "existing-secret" if existing == "matching" else "new-secret"
    )
    if existing == "matching":
        enrollment.issue_grant.assert_not_awaited()
        enrollment.exchange_grant.assert_not_awaited()
    else:
        enrollment.issue_grant.assert_awaited_once()
        enrollment.exchange_grant.assert_awaited_once()
    if existing == "missing":
        enrollment.authenticate_credential.assert_not_awaited()
    else:
        enrollment.authenticate_credential.assert_awaited_once()
