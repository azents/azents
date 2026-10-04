"""Ordinary Runtime Web reads and exact issuance/quota mutation boundaries."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebService,
    RuntimeWebAuthMode,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    ReadSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.runtime_web.gateway_data import RuntimeWebDesiredConfiguration
from azents.repos.runtime_web.gateway_repository import RuntimeWebGatewayRepository
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
)
from azents.repos.runtime_web.repository_test import (
    _authority_fixture,
    _operation,
    _RuntimeWebAuthorityFixture,
)
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate


@asynccontextmanager
async def _committed_authority(
    engine: AsyncEngine,
) -> AsyncIterator[_RuntimeWebAuthorityFixture]:
    writes = create_read_write_session_manager(engine)
    suffix = uuid4().hex
    async with writes() as session:
        fixture = await _authority_fixture(
            session, handle=suffix, email=f"{suffix}@example.test"
        )
    try:
        yield fixture
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == fixture.agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.workspace_id == fixture.workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == fixture.workspace_id)
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(RDBUser.id == fixture.user_id)
            )


@pytest.mark.parametrize("entity", ["service", "configuration"])
async def test_service_and_configuration_reads_complete_under_held_writer(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    entity: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    repository = RuntimeWebRepository()
    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            created = await repository.request_service(
                session,
                workspace_id=fixture.workspace_id,
                agent_id=fixture.agent_id,
                port=3000,
                label="Retained",
                operation=_operation("read-create", actor_id=fixture.agent_id),
                service_limit=16,
            )
        async with AsyncSession(rdb_engine) as writer:
            query = (
                sa.select(RDBRuntimeWebService.id).where(
                    RDBRuntimeWebService.id == created.service.id
                )
                if entity == "service"
                else sa.select(RDBRuntimeWebAuthConfiguration.id).where(
                    RDBRuntimeWebAuthConfiguration.id == 1
                )
            )
            assert await writer.scalar(query.with_for_update()) is not None
            async with reads() as session:
                observed = await asyncio.wait_for(
                    repository.get_service(
                        session, agent_id=fixture.agent_id, port=3000
                    ),
                    timeout=2,
                )
                assert observed == created.service
                assert (
                    await asyncio.wait_for(
                        repository.get_configuration(session), timeout=2
                    )
                    is not None
                )
                page = await repository.list_services(
                    session, agent_id=fixture.agent_id, offset=0, limit=10
                )
                assert page.items == [created.service]


async def test_competing_expected_revision_updates_have_one_winner(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeWebRepository()
    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            created = await repository.request_service(
                session,
                workspace_id=fixture.workspace_id,
                agent_id=fixture.agent_id,
                port=3000,
                label=None,
                operation=_operation("revision-create", actor_id=fixture.agent_id),
                service_limit=16,
            )
        barrier = asyncio.Barrier(2)

        async def update(label: str) -> str:
            try:
                async with writes() as session:
                    await barrier.wait()
                    await repository.update_service(
                        session,
                        service_id=created.service.id,
                        expected_revision=created.service.revision,
                        label_present=True,
                        label=label,
                        selected_duration_seconds=None,
                        operation=_operation(label, actor_id=fixture.agent_id),
                    )
                return "updated"
            except RuntimeWebRepositoryConflict:
                return "conflict"

        assert sorted(await asyncio.gather(update("first"), update("second"))) == [
            "conflict",
            "updated",
        ]


@pytest.mark.parametrize("competitor", ["reset", "off"])
async def test_reset_expiration_preserves_revision_and_never_revives_off(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    competitor: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeWebRepository()
    barrier = asyncio.Barrier(2)
    gate = asyncio.Event()
    release = asyncio.Event()

    class PausedReset(RuntimeWebRepository):
        async def _database_now(self, session: ReadSession) -> datetime:
            if competitor == "reset":
                await barrier.wait()
            else:
                gate.set()
                await release.wait()
            return await super()._database_now(session)

    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            created = await repository.request_service(
                session,
                workspace_id=fixture.workspace_id,
                agent_id=fixture.agent_id,
                port=3000,
                label=None,
                operation=_operation("reset-create", actor_id=fixture.agent_id),
                service_limit=16,
            )
            on = await repository.turn_on(
                session,
                service_id=created.service.id,
                expected_revision=created.service.revision,
                selected_duration_seconds=None,
                operation=_operation("reset-on", actor_id=fixture.agent_id),
                active_agent_limit=16,
            )

        async def reset(key: str) -> str:
            try:
                async with writes() as session:
                    await PausedReset().reset_expiration(
                        session,
                        service_id=on.service.id,
                        expected_revision=on.service.revision,
                        operation=_operation(key, actor_id=fixture.agent_id),
                    )
                return "reset"
            except RuntimeWebRepositoryConflict:
                return "conflict"

        if competitor == "reset":
            results = await asyncio.wait_for(
                asyncio.gather(reset("reset-a"), reset("reset-b")), timeout=3
            )
            assert sorted(results) == ["conflict", "reset"]
        else:
            pending = asyncio.create_task(reset("reset-delayed"))
            try:
                await asyncio.wait_for(gate.wait(), timeout=2)
                async with writes() as session:
                    await repository.turn_off(
                        session,
                        service_id=on.service.id,
                        expected_revision=on.service.revision,
                        operation=_operation("off-winner", actor_id=fixture.agent_id),
                    )
                release.set()
                assert await asyncio.wait_for(pending, timeout=3) == "conflict"
                async with writes() as session:
                    stored = await repository.get_service(
                        session, agent_id=fixture.agent_id, port=3000
                    )
                    assert stored is not None
                    assert stored.exposure_deadline_at is None
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)


async def test_competing_active_slot_admission_preserves_hard_quota(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    repository = RuntimeWebRepository()
    async with _committed_authority(rdb_engine) as fixture:
        services = []
        async with writes() as session:
            for port in [3000, 3001]:
                created = await repository.request_service(
                    session,
                    workspace_id=fixture.workspace_id,
                    agent_id=fixture.agent_id,
                    port=port,
                    label=None,
                    operation=_operation(str(port), actor_id=fixture.agent_id),
                    service_limit=16,
                )
                services.append(created.service)
        barrier = asyncio.Barrier(2)

        async def activate(index: int) -> str:
            try:
                async with writes() as session:
                    await barrier.wait()
                    await repository.turn_on(
                        session,
                        service_id=services[index].id,
                        expected_revision=services[index].revision,
                        selected_duration_seconds=None,
                        operation=_operation(f"on-{index}", actor_id=fixture.agent_id),
                        active_agent_limit=1,
                    )
                return "on"
            except RuntimeWebRepositoryQuotaExceeded as error:
                assert error.scope == "agent_active"
                return "quota"

        assert sorted(await asyncio.gather(activate(0), activate(1))) == ["on", "quota"]


async def test_same_mode_configuration_change_revokes_inflight_issued_identity(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    repository = RuntimeWebGatewayRepository()
    now = datetime.now(UTC)
    async with _committed_authority(rdb_engine) as fixture:
        async with writes() as session:
            auth = await SessionRepository().create(
                session,
                SessionCreate(
                    user_id=fixture.user_id,
                    refresh_token=uuid4().hex,
                    expires_at=now + timedelta(hours=1),
                    max_expires_at=None,
                    user_agent=None,
                    ip_address=None,
                ),
            )
            await repository.synchronize_configuration(
                session,
                desired=RuntimeWebDesiredConfiguration(
                    enabled=True,
                    mode=RuntimeWebAuthMode.SHARED_COOKIE,
                    fingerprint="a" * 64,
                ),
            )
        attempted = asyncio.Event()

        def observe(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            if (
                "runtime_web_auth_configuration" in statement
                and "FOR UPDATE" in statement
            ):
                attempted.set()

        async def revoke() -> None:
            async with writes() as session:
                await repository.synchronize_configuration(
                    session,
                    desired=RuntimeWebDesiredConfiguration(
                        enabled=True,
                        mode=RuntimeWebAuthMode.SHARED_COOKIE,
                        fingerprint="b" * 64,
                    ),
                )

        async with writes() as issuing:
            identity = await repository.create_identity(
                issuing,
                secret_hash="x" * 64,
                user_id=fixture.user_id,
                auth_session_id=auth.id,
                issued_at=now,
                expires_at=now + timedelta(minutes=20),
            )
            event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe)
            task = asyncio.create_task(revoke())
            try:
                await asyncio.wait_for(attempted.wait(), timeout=2)
                # The issued identity commits before the waiting revoke sweep.
                await issuing.write_session.commit()
                await asyncio.wait_for(task, timeout=3)
            finally:
                event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        async with reads() as session:
            assert not await repository.identity_authority_current(
                session,
                identity_id=identity.id,
                user_id=fixture.user_id,
                auth_session_id=auth.id,
                now=now,
            )
