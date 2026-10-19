"""Real opposing Session/archive and Binding/disconnect transaction writers."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from psycopg.errors import DeadlockDetected
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConversationLocation,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.management import ExternalChannelManagementRepository
from azents.repos.external_channel.management_operations import (
    ExternalChannelManagementOperationRepository,
)
from azents.repos.external_channel.participation_operations import (
    ExternalChannelParticipationOperations,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.lifecycle_target import LifecycleSession, LifecycleTargetRepository
from azents.repos.lifecycle_target_test import lifecycle_pipeline
from azents.repos.routine.persistence_test import _legacy_binding, _subject
from azents.repos.session_archive_operations import SessionArchiveOperations
from azents.repos.session_primary_channel import SessionPrimaryChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


class _PausedArchiveTargets(LifecycleTargetRepository):
    """Pause after the production Session lock, only on the first attempt."""

    def __init__(self, reached: asyncio.Event, release: asyncio.Event) -> None:
        self.reached = reached
        self.release = release
        self.paused = False

    async def lock_target_sessions(
        self, session: WriteSession, *, root_session_id: str
    ) -> list[LifecycleSession]:
        result = await super().lock_target_sessions(
            session, root_session_id=root_session_id
        )
        if not self.paused:
            self.paused = True
            self.reached.set()
            await self.release.wait()
        return result


class _PausedBindingTermination(ExternalChannelManagementRepository):
    """Pause after real Connection/Route/Resource/Binding locks, before Primary."""

    def __init__(self, reached: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self.reached = reached
        self.release = release
        self.paused = False

    async def terminate_binding(
        self,
        session: WriteSession,
        *,
        binding: RDBExternalChannelBinding,
        resource: RDBExternalChannelResource,
        now: datetime.datetime,
        reason: str,
    ) -> tuple[ProviderEffectPlan, ...]:
        if not self.paused:
            self.paused = True
            self.reached.set()
            await self.release.wait()
        return await super().terminate_binding(
            session, binding=binding, resource=resource, now=now, reason=reason
        )


@pytest.mark.parametrize("victim", ["archive", "disconnect"])
@pytest.mark.parametrize(
    "terminal_owner", ["binding", "single_begin", "default_clear", "parent_settings"]
)
async def test_archive_and_primary_disconnect_retry_only_confirmed_db_abort(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    victim: str,
    terminal_owner: str,
) -> None:
    """Both actual owning operations settle whichever real transaction loses."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    attempts: dict[str, int] = {}
    aborts: list[str] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        task = asyncio.current_task()
        assert task is not None
        role = task.get_name()
        if role in {"archive", "disconnect"}:
            attempts[role] = attempts.get(role, 0) + 1
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            if role in {"archive", "disconnect"}:
                await raw.execute(
                    sa.text("SELECT set_config('deadlock_timeout', :value, true)"),
                    {"value": "100ms" if role == victim else "5s"},
                )
            try:
                yield ReadWriteSession(raw)
                await raw.commit()
            except BaseException as error:
                await raw.rollback()
                if isinstance(error, OperationalError) and isinstance(
                    error.orig, DeadlockDetected
                ):
                    aborts.append(role)
                raise

    async with committed_fixture_graph(rdb_engine, metadata):
        async with manager() as session:
            scope = await _subject(session)
            binding = await _legacy_binding(session, scope)
            binding_id = binding.id
            resource = await session.write_session.get(
                RDBExternalChannelResource, binding.resource_id
            )
            assert resource is not None
            connection = await session.write_session.get(
                RDBExternalChannelConnection, resource.connection_id
            )
            route = await session.write_session.get(
                RDBExternalChannelAgentRoute, binding.route_id
            )
            assert connection is not None and route is not None
            assert connection.provider_tenant_id is not None
            connection_id = connection.id
            principal = RDBExternalChannelPrincipal(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id=connection.provider_tenant_id,
                provider_user_id=f"principal-{binding_id}",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            )
            session.write_session.add(principal)
            await session.write_session.flush()
            if terminal_owner in {"default_clear", "parent_settings"}:
                resource.resource_type = ExternalChannelResourceType.PARENT_CHANNEL
            if terminal_owner == "default_clear":
                connection.app_mode = ExternalChannelAppMode.MULTI
                route.connection_app_mode = ExternalChannelAppMode.MULTI
                session.write_session.add(
                    RDBExternalChannelChannelDefault(
                        connection_id=connection.id,
                        provider_channel_id=resource.provider_resource_key,
                        route_id=route.id,
                        status=ExternalChannelChannelDefaultStatus.ACTIVE,
                        configured_by_principal_id=principal.id,
                    )
                )
            setting = RDBExternalChannelParticipationSetting(
                connection_id=connection.id,
                provider_parent_channel_id=resource.provider_resource_key,
                route_id=route.id,
                location=ExternalChannelConversationLocation.CHANNEL,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                settings_generation=1,
                status=ExternalChannelParticipationSettingStatus.ACTIVE,
                configured_by_principal_id=principal.id,
            )
            session.write_session.add(setting)
            await session.write_session.flush()
            await session.write_session.refresh(connection)
            connection_generation = connection.updated_at
            setting_id = setting.id
            parent_id = resource.provider_resource_key
            principal_id = principal.id
            await SessionPrimaryChannelRepository().backfill(session)
            generation = await session.write_session.scalar(
                sa.select(RDBAgentSession.owner_generation).where(
                    RDBAgentSession.id == scope.session_id
                )
            )
            assert generation is not None
        archive_reached, binding_reached = asyncio.Event(), asyncio.Event()
        release = asyncio.Event()
        targets = _PausedArchiveTargets(archive_reached, release)
        archive = SessionArchiveOperations(
            session_manager=manager,
            targets=targets,
            run_repository=AgentRunRepository(),
            lifecycle=lifecycle_pipeline(),
        )
        disconnect = ExternalChannelManagementOperationRepository(
            domain_repository=ExternalChannelRepository(),
            repository=_PausedBindingTermination(binding_reached, release),
            lifecycle_repository=ExternalChannelLifecycleRepository.create(),
            agent_repository=AgentRepository(),
            agent_admin_repository=AgentAdminRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            session_manager=manager,
        )
        now = datetime.datetime.now(datetime.UTC)
        terminal_operation: Coroutine[object, object, object]
        if terminal_owner == "single_begin":
            terminal_operation = disconnect._begin_connection_disconnect(
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                connection_id=connection_id,
                now=now,
            )
        elif terminal_owner == "default_clear":
            terminal_operation = disconnect.clear_multi_channel_default(
                workspace_id=scope.workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.SLACK,
                provider_channel_id=parent_id,
                expected_generation=connection_generation,
                now=now,
            )
        elif terminal_owner == "parent_settings":
            participation = ExternalChannelParticipationOperations(
                session_manager=manager,
                read_session_manager=manager,
                repository=ExternalChannelRepository(),
                management_repository=disconnect.repository,
                agent_repository=AgentRepository(),
                workspace_repository=WorkspaceRepository(),
            )
            terminal_operation = participation.mutate_parent_settings(
                connection_id=connection_id,
                provider_parent_channel_id=parent_id,
                principal_id=principal_id,
                expected_setting_id=setting_id,
                expected_settings_generation=1,
                location=ExternalChannelConversationLocation.THREADS,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                now=now,
            )
        else:
            terminal_operation = disconnect.disconnect_binding(
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                agent_session_id=scope.session_id,
                binding_id=binding_id,
                now=now,
            )
        archive_task: asyncio.Task[object] | None = None
        disconnect_task: asyncio.Task[object] | None = None
        try:
            archive_task = asyncio.create_task(
                archive.archive(
                    root_session_id=scope.session_id,
                    expected_owner_generation=generation,
                ),
                name="archive",
            )
            await asyncio.wait_for(archive_reached.wait(), timeout=5)
            disconnect_task = asyncio.create_task(
                terminal_operation,
                name="disconnect",
            )
            await asyncio.wait_for(binding_reached.wait(), timeout=5)
            release.set()
            await asyncio.wait_for(
                asyncio.gather(archive_task, disconnect_task), timeout=15
            )
        finally:
            release.set()
            for task in (archive_task, disconnect_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (archive_task, disconnect_task) if task is not None),
                return_exceptions=True,
            )
        assert aborts and set(aborts) == {victim}
        assert attempts[victim] == len(aborts) + 1
        assert attempts["disconnect" if victim == "archive" else "archive"] == 1
        async with manager() as session:
            root = await session.write_session.get(RDBAgentSession, scope.session_id)
            current_binding = await session.write_session.get(
                RDBExternalChannelBinding, binding_id
            )
            assert root is not None and root.status is AgentSessionStatus.ARCHIVED
            assert root.primary_channel_binding_id is None
            assert current_binding is not None
            assert current_binding.disconnected_at is not None
