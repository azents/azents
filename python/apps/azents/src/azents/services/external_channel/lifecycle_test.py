"""External Channel lifecycle service dispatch tests."""

import datetime
from collections.abc import Sequence
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
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
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)
from azents.repos.external_channel.lifecycle import (
    ExternalChannelLifecycleRepository,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)


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


def _plan() -> ProviderEffectPlan:
    return ProviderEffectPlan(
        target=ProviderTarget(
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            binding_id="binding-1",
            resource_id="resource-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="encrypted",
            provider_tenant_id="tenant-1",
            capabilities=None,
            provider_configuration=None,
            workspace_handle="workspace",
            agent_id="agent-1",
            agent_session_id="session-1",
            agent_name="Agent",
            agent_avatar=None,
            request_payload={"control_kind": "session_presence"},
        ),
        operation_key=ProviderOperationKey.from_seed("archive-cleanup"),
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
        del session, now
        self.calls.append(("archive", tuple(session_ids)))
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=1,
            finished_work_count=1,
            direct_cleanup_count=1,
            cleanup_plans=(_plan(),),
        )

    async def validate_restore_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelRestoreValidation:
        del session
        self.calls.append(("restore", tuple(session_ids)))
        return ExternalChannelRestoreValidation(
            disconnected_binding_count=1,
            finished_work_count=1,
        )

    async def purge_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeCleanup:
        del session
        self.calls.append(("cleanup", tuple(session_ids)))
        return ExternalChannelPurgeCleanup(
            deleted_session_grant_count=1,
            preserved_agent_grant_reference_count=1,
            deleted_access_request_count=1,
            deleted_work_count=1,
            deleted_binding_count=1,
        )

    async def verify_session_tree_purged(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeVerification:
        del session
        self.calls.append(("verify", tuple(session_ids)))
        return ExternalChannelPurgeVerification(
            remaining_binding_count=0,
            remaining_work_count=0,
            remaining_access_request_count=0,
            remaining_session_grant_count=0,
        )


class _ActionServiceDouble:
    def __init__(self) -> None:
        self.plans: list[ProviderEffectPlan] = []

    async def execute_terminal_control(self, plan: ProviderEffectPlan) -> None:
        self.plans.append(plan)


def _service(
    repository: _RepositoryDouble,
    action_service: _ActionServiceDouble | None = None,
) -> ExternalChannelLifecycleService:
    return ExternalChannelLifecycleService(
        repository=repository,
        action_service=cast(
            ExternalChannelActionService,
            action_service or _ActionServiceDouble(),
        ),
    )


@pytest.mark.asyncio
async def test_external_channel_dispatches_only_its_participant(
    rdb_session: AsyncSession,
) -> None:
    repository = _RepositoryDouble()
    service = _service(repository)

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
    assert archive.direct_cleanup_count == 1
    assert restore is not None
    assert repository.calls == [
        ("archive", ("session-1", "session-2")),
        ("restore", ("session-1", "session-2")),
    ]


@pytest.mark.asyncio
async def test_purge_has_no_provider_delivery_preparation(
    rdb_session: AsyncSession,
) -> None:
    repository = _RepositoryDouble()
    service = _service(repository)
    definition = _definition("session.external-channel")
    context = _purge_context()

    assert (
        await service.prepare_purge_participant(
            rdb_session,
            definition,
            context,
        )
        is None
    )
    await service.cleanup_purge_participant(rdb_session, definition, context)
    await service.verify_purge_participant(rdb_session, definition, context)
    await service.finalize_purge_participant(rdb_session, definition, context)

    assert repository.calls == [
        ("cleanup", ("session-1", "session-2")),
        ("verify", ("session-1", "session-2")),
        ("verify", ("session-1", "session-2")),
    ]


@pytest.mark.asyncio
async def test_archive_cleanup_executes_each_captured_plan_once() -> None:
    repository = _RepositoryDouble()
    action_service = _ActionServiceDouble()
    service = _service(repository, action_service)
    plans = (_plan(), _plan())

    consumed = await service.consume_archive_cleanup(plans)

    assert consumed == 2
    assert action_service.plans == list(plans)
