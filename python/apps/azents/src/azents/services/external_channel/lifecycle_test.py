"""External Channel lifecycle service dispatch tests."""

import datetime
from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelBindingStatus, ExternalChannelWorkStatus
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
    SessionLifecyclePurgePolicy,
    SessionLifecycleTransitionContext,
    SessionLifecycleTransitionPolicy,
)
from azents.repos.external_channel.data import (
    ExternalChannelArchiveTermination,
    ExternalChannelPurgeCleanup,
    ExternalChannelPurgePreparation,
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)
from azents.repos.external_channel.lifecycle import (
    ExternalChannelLifecycleRepository,
)
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService


def _definition(key: str) -> SessionLifecycleParticipantDefinition:
    """Build a minimal lifecycle definition for dispatch coverage."""
    return SessionLifecycleParticipantDefinition(
        key=key,
        policy_version=1,
        dependencies=(),
        owned_resources=(),
        archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
        restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
        purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
    )


def _transition_context() -> SessionLifecycleTransitionContext:
    """Build a stable locked Session tree context."""
    return SessionLifecycleTransitionContext(
        transition_id="transition-1",
        root_session_id="session-1",
        subtree_session_ids=("session-1", "session-2"),
    )


def _purge_context() -> SessionLifecyclePurgeContext:
    """Build a stable fenced purge context."""
    return SessionLifecyclePurgeContext(
        purge_job_id="job-1",
        lease_owner="scheduler-1",
        root_session_id="session-1",
        subtree_session_ids=("session-1", "session-2"),
    )


class _RepositoryDouble(ExternalChannelLifecycleRepository):
    """Repository double recording transaction-bound lifecycle calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def terminate_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        now: datetime.datetime,
    ) -> ExternalChannelArchiveTermination:
        """Record archive termination without a provider operation."""
        del session, now
        self.calls.append(("archive", tuple(session_ids)))
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=1,
            finished_work_count=1,
            deleted_pending_context_count=1,
            created_progress_delete_intent_count=1,
        )

    async def validate_restore_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelRestoreValidation:
        """Record restore validation."""
        del session
        self.calls.append(("restore", tuple(session_ids)))
        return ExternalChannelRestoreValidation(
            disconnected_binding_count=1,
            finished_work_count=1,
        )

    async def prepare_session_tree_purge(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        now: datetime.datetime,
    ) -> ExternalChannelPurgePreparation:
        """Record provider-free purge preparation."""
        del session, now
        self.calls.append(("prepare", tuple(session_ids)))
        return ExternalChannelPurgePreparation(
            not_attempted_delivery_count=1,
            unknown_delivery_count=1,
        )

    async def purge_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeCleanup:
        """Record restrictive Session-owned cleanup."""
        del session
        self.calls.append(("cleanup", tuple(session_ids)))
        return ExternalChannelPurgeCleanup(
            deleted_delivery_attempt_count=1,
            deleted_action_count=1,
            deleted_session_grant_count=1,
            preserved_agent_grant_reference_count=1,
            deleted_access_request_count=1,
            deleted_invocation_batch_item_count=1,
            deleted_invocation_batch_count=1,
            deleted_work_count=1,
            deleted_binding_count=1,
        )

    async def verify_session_tree_purged(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeVerification:
        """Record final absence verification."""
        del session
        self.calls.append(("verify", tuple(session_ids)))
        return ExternalChannelPurgeVerification(
            remaining_binding_count=0,
            remaining_work_count=0,
            remaining_action_count=0,
            remaining_delivery_attempt_count=0,
            remaining_access_request_count=0,
            remaining_session_grant_count=0,
            remaining_invocation_batch_count=0,
        )


class _RowsDouble:
    """Minimal SQLAlchemy scalar result used by lifecycle repository unit tests."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        """Return preselected rows."""
        return self.rows


class _ExecutionDouble:
    """Minimal execute result supporting lifecycle row counts and inserts."""

    def scalar_one_or_none(self) -> None:
        """Model an idempotent insert that already has its delivery identity."""
        return None

    def scalars(self) -> _RowsDouble:
        """Model a mutation that affected no rows."""
        return _RowsDouble([])


class _LifecycleSessionDouble:
    """Record lifecycle SQL while supplying deterministic scalar query results."""

    def __init__(self, scalar_rows: list[list[object]]) -> None:
        self.scalar_rows = scalar_rows
        self.scalar_statements: list[sa.ClauseElement] = []
        self.execute_statements: list[sa.ClauseElement] = []

    async def scalars(self, statement: sa.ClauseElement) -> _RowsDouble:
        """Return rows for one lifecycle select in call order."""
        self.scalar_statements.append(statement)
        return _RowsDouble(self.scalar_rows.pop(0))

    async def execute(self, statement: sa.ClauseElement) -> _ExecutionDouble:
        """Record a lifecycle insert, update, or delete."""
        self.execute_statements.append(statement)
        return _ExecutionDouble()

    async def flush(self) -> None:
        """Model caller-owned transaction flushing."""


@pytest.mark.asyncio
async def test_archive_selects_only_active_work_for_progress_cleanup() -> None:
    """A historical finished work cannot produce a new progress-delete intent."""
    binding = SimpleNamespace(
        id="binding-1",
        resource_id="resource-1",
        status=ExternalChannelBindingStatus.ACTIVE,
        disconnected_at=None,
        disconnect_reason=None,
    )
    active_work = SimpleNamespace(
        id="work-active",
        binding_id="binding-1",
        status=ExternalChannelWorkStatus.ACTIVE,
        finished_at=None,
        desired_progress_payload={"status": "working"},
        desired_progress_revision=3,
        progress_provider_message_key="progress-message-1",
    )
    session = _LifecycleSessionDouble([[binding], [active_work]])

    await ExternalChannelLifecycleRepository().terminate_session_tree(
        cast(AsyncSession, session),
        session_ids=("session-1",),
        now=datetime.datetime(2026, 7, 21, tzinfo=datetime.UTC),
    )

    work_select = str(session.scalar_statements[1])
    progress_insert = session.execute_statements[0].compile().params
    assert progress_insert is not None
    assert "external_channel_works.status =" in work_select
    assert active_work.desired_progress_payload is None
    assert active_work.desired_progress_revision == 4
    assert progress_insert["id"]
    assert progress_insert["origin_id"] == "binding-1"


@pytest.mark.asyncio
async def test_purge_delivery_cleanup_includes_binding_null_action_attempts() -> None:
    """An action-linked delivery is removed before its owning action is deleted."""
    session = _LifecycleSessionDouble([[], [], ["action-1"], []])

    await ExternalChannelLifecycleRepository().purge_session_tree(
        cast(AsyncSession, session),
        session_ids=("session-1",),
    )

    delivery_delete = str(session.execute_statements[0])
    assert "external_channel_delivery_attempts.channel_action_id IN" in delivery_delete


@pytest.mark.asyncio
async def test_external_channel_dispatches_only_its_participant(
    rdb_session: AsyncSession,
) -> None:
    """Archive and restore invoke only the External Channel participant."""
    repository = _RepositoryDouble()
    service = ExternalChannelLifecycleService(repository=repository)

    assert (
        await service.archive_participant(
            rdb_session,
            _definition("session.other"),
            _transition_context(),
        )
        is None
    )
    archive = await service.archive_participant(
        rdb_session,
        _definition("session.external-channel"),
        _transition_context(),
    )
    restore = await service.restore_participant(
        rdb_session,
        _definition("session.external-channel"),
        _transition_context(),
    )

    assert archive is not None
    assert restore is not None
    assert repository.calls == [
        ("archive", ("session-1", "session-2")),
        ("restore", ("session-1", "session-2")),
    ]


@pytest.mark.asyncio
async def test_external_channel_purge_phases_are_transaction_bound(
    rdb_session: AsyncSession,
) -> None:
    """Purge phase calls remain inside the caller-owned DB transaction."""
    repository = _RepositoryDouble()
    service = ExternalChannelLifecycleService(repository=repository)
    definition = _definition("session.external-channel")
    context = _purge_context()

    await service.prepare_purge_participant(rdb_session, definition, context)
    await service.cleanup_purge_participant(rdb_session, definition, context)
    await service.verify_purge_participant(rdb_session, definition, context)
    await service.finalize_purge_participant(rdb_session, definition, context)

    assert repository.calls == [
        ("prepare", ("session-1", "session-2")),
        ("cleanup", ("session-1", "session-2")),
        ("verify", ("session-1", "session-2")),
        ("verify", ("session-1", "session-2")),
    ]
