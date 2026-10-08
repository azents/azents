"""Genuine PostgreSQL ingress read commits, detached results and closure."""

import asyncio
import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, NamedTuple

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
)
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
    RDBExternalChannelIngressOwner,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.app_mode_repository_test import (
    _agent,
    _connection_create,
    _resource,
    _route_create,
    _workspace,
)
from azents.repos.external_channel.data import (
    ExternalChannelConversationPositionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.ingress_control_read import (
    ExternalChannelIngressControlReadRepository,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressDiagnosticSnapshot,
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressOwner,
    ExternalChannelIngressOwnerCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository

_NOW = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)
_MISSING = "0" * 32


class _Seed(NamedTuple):
    owner_id: str
    item_ids: tuple[str, ...]


async def _seed(manager: SessionManager[WriteSession]) -> _Seed:
    """Create isolated relational queue inputs outside the completed reads."""
    async with manager() as session:
        workspace_id = await _workspace(session, "ingress-control-read")
        agent = await _agent(session, workspace_id, "ingress-control-read")
        repository = ExternalChannelRepository()
        connection = await repository.create_connection(
            session, _connection_create(workspace_id)
        )
        route = await repository.create_agent_route(
            session,
            _route_create(connection.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
        )
        resource = await _resource(
            session, repository, connection_id=connection.id, key="read-thread"
        )
        position = await repository.create_conversation_position_idempotent(
            session,
            ExternalChannelConversationPositionCreate(
                connection_id=connection.id,
                scope_kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id="private-channel",
                provider_thread_key="private-thread",
                read_through_position=None,
            ),
        )
        principal = await repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="private-tenant",
                provider_user_id="private-user",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        )
        owner_create = ExternalChannelIngressOwnerCreate(
            connection_id=connection.id,
            target_resource_id=resource.id,
            route_id=route.id,
            participation_setting_id=None,
            participation_settings_generation=None,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            binding_id=None,
            session_id=None,
        )
        queue = ExternalChannelIngressQueueRepository()
        ids: list[str] = []
        owner_id = None
        for index in range(3):
            admission = await queue.admit(
                session,
                owner_create=owner_create,
                item_create=ExternalChannelIngressItemCreate(
                    deduplication_key=f"{index:064d}",
                    provider_event_id=f"private-event-{index}",
                    connection_id=connection.id,
                    provider=ExternalChannelProvider.SLACK,
                    ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
                    configuration_generation=connection.configuration_generation,
                    authority_kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
                    authority_lease_owner=None,
                    authority_lease_generation=None,
                    provider_event_type="message",
                    provider_tenant_id="private-tenant",
                    scope_kind=ExternalChannelConversationScopeKind.THREAD,
                    provider_channel_id="private-channel",
                    provider_parent_channel_id=None,
                    provider_thread_key="private-thread",
                    delivery_thread_key="private-thread",
                    provider_resource_key="read-thread",
                    source_resource_id=resource.id,
                    conversation_position_id=position.id,
                    principal_id=principal.id,
                    trigger_provider_message_key=f"private-message-{index}",
                    trigger_provider_message_id=f"{index}.0",
                    trigger_position=f"{index:020d}",
                    provider_user_id="private-user",
                    invocation=True,
                    expected_file_count=None,
                    invocation_id=f"private-invocation-{index}",
                    initial_title_eligible=False,
                ),
            )
            owner_id = admission.owner.id
            ids.append(admission.item.id)
            await session.write_session.execute(
                sa.update(RDBExternalChannelIngressItem)
                .where(RDBExternalChannelIngressItem.id == admission.item.id)
                .values(
                    queue_key=f"{index:032d}",
                    created_at=_NOW + datetime.timedelta(seconds=index),
                )
            )
        assert owner_id is not None
        await session.write_session.execute(
            sa.update(RDBExternalChannelIngressOwner)
            .where(RDBExternalChannelIngressOwner.id == owner_id)
            .values(created_at=_NOW)
        )
        await session.write_session.execute(
            sa.update(RDBExternalChannelIngressItem)
            .where(RDBExternalChannelIngressItem.id == ids[1])
            .values(
                state=ExternalChannelIngressItemState.PROCESSING,
                processing_owner="processor",
                processing_generation=1,
                batch_id="b" * 32,
            )
        )
        await session.write_session.execute(
            sa.update(RDBExternalChannelIngressItem)
            .where(RDBExternalChannelIngressItem.id == ids[2])
            .values(
                state=ExternalChannelIngressItemState.RETRY_WAITING,
                next_attempt_at=_NOW + datetime.timedelta(minutes=1),
            )
        )
    return _Seed(owner_id, tuple(ids))


class _Boundary:
    """Track actual Session transactions and real commit events."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.opened: list[WriteSession] = []
        self.active: list[WriteSession] = []
        self.events: list[str] = []

    @asynccontextmanager
    async def session_manager(self) -> AsyncIterator[WriteSession]:
        current: WriteSession | None = None

        def committed(_: object) -> None:
            self.events.append("commit")

        try:
            async with self.manager() as session:
                current = session
                self.opened.append(session)
                self.active.append(session)
                self.events.append("open")
                event.listen(
                    session.write_session.sync_session, "after_commit", committed
                )
                yield session
        finally:
            if current is not None:
                self.active.remove(current)
                event.remove(
                    current.write_session.sync_session, "after_commit", committed
                )
                self.events.append("closed")

    def closed(self) -> None:
        assert not self.active
        assert all(
            not session.write_session.in_transaction() for session in self.opened
        )


def _reads(
    boundary: _Boundary, queue: ExternalChannelIngressQueueRepository
) -> ExternalChannelIngressControlReadRepository:
    return ExternalChannelIngressControlReadRepository(
        session_manager=boundary.session_manager, queue_repository=queue
    )


async def test_empty_owner_and_diagnostics_explicitly_commit_before_return(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    boundary = _Boundary(rdb_session_manager)
    repository = _reads(boundary, ExternalChannelIngressQueueRepository())
    assert await repository.get_release_owner(owner_id=_MISSING) is None
    boundary.closed()
    assert boundary.events == ["open", "commit", "commit", "closed"]
    boundary.events.clear()
    snapshot = await repository.inspect_active(now=_NOW, limit=200)
    boundary.closed()
    assert snapshot.owner_count == snapshot.counts.total == 0
    assert snapshot.items == () and not snapshot.truncated
    assert boundary.events == ["open", "commit", "commit", "closed"]


async def test_owner_read_uses_presence_without_ready_lease_or_due_filters(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    seed = await _seed(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBExternalChannelIngressOwner)
            .where(RDBExternalChannelIngressOwner.id == seed.owner_id)
            .values(
                preparation_next_attempt_at=_NOW + datetime.timedelta(days=1),
                lease_owner="busy-owner",
                lease_acquired_at=_NOW,
                lease_expires_at=_NOW + datetime.timedelta(days=1),
            )
        )
    boundary = _Boundary(rdb_session_manager)
    owner = await _reads(
        boundary, ExternalChannelIngressQueueRepository()
    ).get_release_owner(owner_id=seed.owner_id)
    boundary.closed()
    assert owner is not None and not owner.ready
    assert owner.created_at == _NOW
    assert owner.lease_owner == "busy-owner"
    assert owner.preparation_next_attempt_at == _NOW + datetime.timedelta(days=1)
    assert boundary.events == ["open", "commit", "commit", "closed"]


@pytest.mark.parametrize("limit", [1, 3, 1000])
async def test_sanitized_counts_order_age_and_truncation_remain_detached(
    rdb_session_manager: SessionManager[WriteSession], limit: int
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)
    snapshot = await _reads(
        boundary, ExternalChannelIngressQueueRepository()
    ).inspect_active(now=_NOW + datetime.timedelta(seconds=60), limit=limit)
    boundary.closed()
    assert snapshot.owner_count == 1
    assert snapshot.counts.pending == snapshot.counts.processing == 1
    assert snapshot.counts.retry_waiting == 1
    assert snapshot.oldest_queue_age_seconds == 60
    assert [item.id for item in snapshot.items] == list(seed.item_ids[:limit])
    assert snapshot.truncated == (limit < 3)
    assert (
        snapshot.items[0].item_age_seconds == snapshot.items[0].owner_age_seconds == 60
    )
    serialized = json.dumps(snapshot.model_dump(mode="json"))
    for private in [
        "private-user",
        "private-tenant",
        "private-channel",
        "private-thread",
        "private-message",
        "private-invocation",
        "principal_id",
        "credential",
        "message_body",
        "trigger_provider_message",
    ]:
        assert private not in serialized


@pytest.mark.parametrize("limit", [0, 1001])
async def test_diagnostic_limit_errors_close_without_metrics_or_commit(
    rdb_session_manager: SessionManager[WriteSession], limit: int
) -> None:
    boundary = _Boundary(rdb_session_manager)
    with pytest.raises(ValueError, match="limit must be from 1 to 1000"):
        await _reads(boundary, ExternalChannelIngressQueueRepository()).inspect_active(
            now=_NOW, limit=limit
        )
    boundary.closed()
    assert boundary.events == ["open", "closed"]


class _ReadFault(ExternalChannelIngressQueueRepository):
    """Raise after an actual query without fabricating SQL completion."""

    def __init__(self, cancel: bool) -> None:
        self.cancel = cancel
        self.reached = False

    def fail(self, session: ReadSession) -> None:
        assert session.read_session.in_transaction()
        self.reached = True
        if self.cancel:
            raise asyncio.CancelledError()
        raise ValueError("after actual ingress read")

    async def get_active_owner(
        self, session: ReadSession, *, owner_id: str
    ) -> ExternalChannelIngressOwner | None:
        await super().get_active_owner(session, owner_id=owner_id)
        self.fail(session)
        return None

    async def inspect_active(
        self, session: ReadSession, *, now: datetime.datetime, limit: int
    ) -> ExternalChannelIngressDiagnosticSnapshot:
        snapshot = await super().inspect_active(session, now=now, limit=limit)
        self.fail(session)
        return snapshot


@pytest.mark.parametrize("operation", ["owner", "diagnostic"])
@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_actual_query_error_and_cancellation_close_before_external_effects(
    rdb_session_manager: SessionManager[WriteSession],
    operation: Literal["owner", "diagnostic"],
    cancel: bool,
) -> None:
    seed = await _seed(rdb_session_manager)
    boundary = _Boundary(rdb_session_manager)
    queue = _ReadFault(cancel)
    reads = _reads(boundary, queue)
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        if operation == "owner":
            await reads.get_release_owner(owner_id=seed.owner_id)
        else:
            await reads.inspect_active(now=_NOW, limit=200)
    boundary.closed()
    assert queue.reached
    assert boundary.events == ["open", "closed"]
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count()).select_from(RDBExternalChannelIngressItem)
            )
            == 3
        )
