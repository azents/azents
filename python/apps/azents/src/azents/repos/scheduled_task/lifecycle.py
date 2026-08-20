"""Scheduled Task persistence operations for owning lifecycle transitions."""

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    ExternalChannelDeliveryOperation,
    MailboxItemKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
)
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.scheduled_task import RDBScheduledTask
from azents.rdb.models.toolkit_state import RDBToolkitState
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.mailbox.data import (
    ScheduledTaskContinuationMailboxPayload,
    ScheduledTaskTriggerMailboxPayload,
)
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleState
from azents.services.external_channel.data import (
    decode_provider_connection_configuration,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)

_NAMESPACE = "scheduled"
_STATE_NAME_PREFIX = "cycle:"


@dataclass(frozen=True)
class ScheduledTaskLifecycleCleanup:
    """Canonical deletion counts and captured post-commit provider work."""

    deleted_task_count: int
    deleted_admitted_cycle_count: int
    deleted_trigger_count: int
    preserved_started_cycle_count: int
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class ScheduledTaskLifecycleVerification:
    """Restrictive Scheduled Task lifecycle absence projection."""

    task_count: int
    trigger_count: int
    admitted_cycle_count: int
    started_cycle_count: int


@dataclass(frozen=True)
class _BindingTarget:
    """Current provider authority captured before Binding terminalization."""

    binding: RDBExternalChannelBinding
    resource: RDBExternalChannelResource
    connection: RDBExternalChannelConnection
    agent_session: RDBAgentSession
    agent: RDBAgent
    workspace: RDBWorkspace | None


class ScheduledTaskLifecycleRepository:
    """Remove pre-start Scheduled authority while preserving started cycles."""

    @classmethod
    def create(cls) -> "ScheduledTaskLifecycleRepository":
        """Create a lifecycle repository for dependency injection."""
        return cls()

    async def terminate_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ScheduledTaskLifecycleCleanup:
        """Delete Session-owned Tasks and admitted work in stable lock order."""
        tasks = list(
            (
                await session.scalars(
                    sa.select(RDBScheduledTask)
                    .where(RDBScheduledTask.session_id.in_(session_ids))
                    .order_by(RDBScheduledTask.id)
                )
            ).all()
        )
        cleanup = await self._terminate_tasks(
            session,
            tasks=tasks,
            expected_binding_id=None,
        )
        remaining_cleanup = await self._cleanup_remaining_lifecycle_work(
            session,
            session_ids=session_ids,
            expected_binding_id=None,
        )
        return ScheduledTaskLifecycleCleanup(
            deleted_task_count=cleanup.deleted_task_count,
            deleted_admitted_cycle_count=(
                cleanup.deleted_admitted_cycle_count
                + remaining_cleanup.deleted_admitted_cycle_count
            ),
            deleted_trigger_count=(
                cleanup.deleted_trigger_count + remaining_cleanup.deleted_trigger_count
            ),
            preserved_started_cycle_count=(
                cleanup.preserved_started_cycle_count
                + remaining_cleanup.preserved_started_cycle_count
            ),
            cleanup_plans=cleanup.cleanup_plans + remaining_cleanup.cleanup_plans,
        )

    async def terminate_binding(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ScheduledTaskLifecycleCleanup:
        """Delete Tasks targeted at one Binding before it is disconnected."""
        tasks = list(
            (
                await session.scalars(
                    sa.select(RDBScheduledTask)
                    .where(RDBScheduledTask.binding_id == binding_id)
                    .order_by(RDBScheduledTask.id)
                )
            ).all()
        )
        cleanup = await self._terminate_tasks(
            session,
            tasks=tasks,
            expected_binding_id=binding_id,
        )
        remaining_cleanup = await self._cleanup_remaining_lifecycle_work(
            session,
            session_ids=None,
            expected_binding_id=binding_id,
        )
        return ScheduledTaskLifecycleCleanup(
            deleted_task_count=cleanup.deleted_task_count,
            deleted_admitted_cycle_count=(
                cleanup.deleted_admitted_cycle_count
                + remaining_cleanup.deleted_admitted_cycle_count
            ),
            deleted_trigger_count=(
                cleanup.deleted_trigger_count + remaining_cleanup.deleted_trigger_count
            ),
            preserved_started_cycle_count=(
                cleanup.preserved_started_cycle_count
                + remaining_cleanup.preserved_started_cycle_count
            ),
            cleanup_plans=cleanup.cleanup_plans + remaining_cleanup.cleanup_plans,
        )

    async def archive_allows_active_runs(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Return whether every active execution is one valid started cycle."""
        runs = list(
            (
                await session.scalars(
                    sa.select(RDBAgentRun)
                    .where(
                        RDBAgentRun.session_id.in_(session_ids),
                        RDBAgentRun.status.in_(
                            (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                        ),
                    )
                    .order_by(RDBAgentRun.session_id, RDBAgentRun.id)
                )
            ).all()
        )
        if not runs and not running_session_ids:
            return True
        active_session_ids: set[str] = set()
        for run in runs:
            cycle_id = run.scheduled_task_cycle_id
            if cycle_id is None:
                return False
            agent_id = await session.scalar(
                sa.select(RDBAgentSession.agent_id).where(
                    RDBAgentSession.id == run.session_id
                )
            )
            if agent_id is None:
                return False
            cycle = await self._cycle(
                session,
                agent_id=agent_id,
                session_id=run.session_id,
                cycle_id=cycle_id,
            )
            if (
                cycle is None
                or cycle.phase != "started"
                or cycle.current_run_id != run.id
            ):
                return False
            active_session_ids.add(run.session_id)
        scheduled_mailbox_session_ids: set[str] = set()
        mailbox_items = list(
            (
                await session.scalars(
                    sa.select(RDBMailboxItem)
                    .where(RDBMailboxItem.session_id.in_(session_ids))
                    .order_by(
                        RDBMailboxItem.session_id,
                        RDBMailboxItem.order_group,
                        RDBMailboxItem.order_sequence,
                        RDBMailboxItem.id,
                    )
                )
            ).all()
        )
        for item in mailbox_items:
            if item.kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
                payload = ScheduledTaskTriggerMailboxPayload.model_validate(
                    item.payload
                )
                if item.idempotency_key != f"scheduled-task-trigger:{payload.cycle_id}":
                    return False
                scheduled_mailbox_session_ids.add(item.session_id)
                continue
            if item.kind is not MailboxItemKind.SCHEDULED_TASK_CONTINUATION:
                return False
            payload = ScheduledTaskContinuationMailboxPayload.model_validate(
                item.payload
            )
            agent_id = await session.scalar(
                sa.select(RDBAgentSession.agent_id).where(
                    RDBAgentSession.id == item.session_id
                )
            )
            if agent_id is None:
                return False
            cycle = await self._cycle(
                session,
                agent_id=agent_id,
                session_id=item.session_id,
                cycle_id=payload.cycle_id,
            )
            if cycle is None or cycle.phase != "started":
                return False
            scheduled_mailbox_session_ids.add(item.session_id)
        allowed_running_session_ids = active_session_ids | scheduled_mailbox_session_ids
        return set(running_session_ids).issubset(allowed_running_session_ids)

    async def validate_restore_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ScheduledTaskLifecycleVerification:
        """Require restore to preserve only already-started independent cycles."""
        verification = await self.verify_session_tree(
            session,
            session_ids=session_ids,
        )
        if (
            verification.task_count
            or verification.trigger_count
            or verification.admitted_cycle_count
        ):
            raise RuntimeError("Restored Scheduled Task authority was recreated.")
        return verification

    async def require_purge_ready(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ScheduledTaskLifecycleVerification:
        """Reject permanent purge while a preserved started cycle remains."""
        verification = await self.verify_session_tree(
            session,
            session_ids=session_ids,
        )
        if verification.started_cycle_count:
            raise RuntimeError(
                "Scheduled Task started cycles remain active for the Session tree."
            )
        return verification

    async def purge_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ScheduledTaskLifecycleCleanup:
        """Delete residual Task and admitted-cycle state before finalization."""
        await self.require_purge_ready(session, session_ids=session_ids)
        return await self.terminate_session_tree(
            session,
            session_ids=session_ids,
        )

    async def verify_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ScheduledTaskLifecycleVerification:
        """Count Task rows and namespaced cycle states for one Session tree."""
        task_count = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBScheduledTask)
                .where(RDBScheduledTask.session_id.in_(session_ids))
            )
            or 0
        )
        trigger_count = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBMailboxItem)
                .where(
                    RDBMailboxItem.session_id.in_(session_ids),
                    RDBMailboxItem.kind == MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                )
            )
            or 0
        )
        states = list(
            (
                await session.scalars(
                    sa.select(RDBToolkitState).where(
                        RDBToolkitState.session_id.in_(session_ids),
                        RDBToolkitState.toolkit_namespace == _NAMESPACE,
                        RDBToolkitState.state_name.startswith(_STATE_NAME_PREFIX),
                    )
                )
            ).all()
        )
        admitted_cycle_count = 0
        started_cycle_count = 0
        for state in states:
            cycle = ScheduledTaskCycleState.model_validate(state.state_json)
            admitted_cycle_count += int(cycle.phase == "admitted")
            started_cycle_count += int(cycle.phase == "started")
        return ScheduledTaskLifecycleVerification(
            task_count=task_count,
            trigger_count=trigger_count,
            admitted_cycle_count=admitted_cycle_count,
            started_cycle_count=started_cycle_count,
        )

    async def _terminate_tasks(
        self,
        session: AsyncSession,
        *,
        tasks: Sequence[RDBScheduledTask],
        expected_binding_id: str | None,
    ) -> ScheduledTaskLifecycleCleanup:
        deleted_task_count = 0
        deleted_admitted_cycle_count = 0
        deleted_trigger_count = 0
        for candidate in tasks:
            trigger: RDBMailboxItem | None = None
            cycle_row: RDBToolkitState | None = None
            cycle: ScheduledTaskCycleState | None = None
            if candidate.active_cycle_id is not None:
                trigger = await self._lock_trigger(
                    session,
                    session_id=candidate.session_id,
                    cycle_id=candidate.active_cycle_id,
                )
                cycle_row = await self._lock_cycle_row(
                    session,
                    agent_id=candidate.agent_id,
                    session_id=candidate.session_id,
                    cycle_id=candidate.active_cycle_id,
                )
                if cycle_row is not None:
                    cycle = ScheduledTaskCycleState.model_validate(cycle_row.state_json)
            task = await session.scalar(
                sa.select(RDBScheduledTask)
                .where(RDBScheduledTask.id == candidate.id)
                .with_for_update()
            )
            if task is None:
                continue
            if task.active_cycle_id != candidate.active_cycle_id:
                raise RuntimeError(
                    "Scheduled Task cycle fence changed during lifecycle cleanup."
                )
            if (
                expected_binding_id is not None
                and task.binding_id != expected_binding_id
            ):
                continue
            if trigger is not None:
                await session.delete(trigger)
                deleted_trigger_count += 1
            if cycle is not None and cycle.phase == "admitted":
                assert cycle_row is not None
                await session.delete(cycle_row)
                deleted_admitted_cycle_count += 1
            await session.delete(task)
            deleted_task_count += 1
        await session.flush()
        return ScheduledTaskLifecycleCleanup(
            deleted_task_count=deleted_task_count,
            deleted_admitted_cycle_count=deleted_admitted_cycle_count,
            deleted_trigger_count=deleted_trigger_count,
            preserved_started_cycle_count=0,
            cleanup_plans=(),
        )

    async def _cleanup_remaining_lifecycle_work(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str] | None,
        expected_binding_id: str | None,
    ) -> ScheduledTaskLifecycleCleanup:
        """Clean cycle-owned work after Task authority has been removed."""
        if (session_ids is None) == (expected_binding_id is None):
            raise ValueError("Scheduled lifecycle cleanup requires one exact scope.")
        query = sa.select(RDBToolkitState).where(
            RDBToolkitState.toolkit_namespace == _NAMESPACE,
            RDBToolkitState.state_name.startswith(_STATE_NAME_PREFIX),
        )
        if session_ids is not None:
            query = query.where(RDBToolkitState.session_id.in_(session_ids))
        if expected_binding_id is not None:
            query = query.where(
                RDBToolkitState.state_json["binding_id"].as_string()
                == expected_binding_id
            )
        candidates = list(
            (await session.scalars(query.order_by(RDBToolkitState.id))).all()
        )
        deleted_cycle_count = 0
        deleted_trigger_count = 0
        preserved_started_cycle_count = 0
        cleanup_plans: list[ProviderEffectPlan] = []
        for candidate in candidates:
            candidate_cycle = ScheduledTaskCycleState.model_validate(
                candidate.state_json
            )
            trigger = await self._lock_trigger(
                session,
                session_id=candidate_cycle.session_id,
                cycle_id=candidate_cycle.cycle_id,
            )
            row = await self._lock_cycle_row(
                session,
                agent_id=candidate_cycle.agent_id,
                session_id=candidate_cycle.session_id,
                cycle_id=candidate_cycle.cycle_id,
            )
            if row is None:
                if trigger is not None:
                    await session.delete(trigger)
                    deleted_trigger_count += 1
                continue
            cycle = ScheduledTaskCycleState.model_validate(row.state_json)
            if (
                expected_binding_id is not None
                and cycle.binding_id != expected_binding_id
            ):
                continue
            if trigger is not None:
                await session.delete(trigger)
                deleted_trigger_count += 1
            if cycle.phase == "admitted":
                await session.delete(row)
                deleted_cycle_count += 1
                continue
            preserved_started_cycle_count += 1
            if cycle.binding_id is not None:
                targets = await self._binding_targets(
                    session,
                    binding_ids=[cycle.binding_id],
                )
                target = targets.get(cycle.binding_id)
                if target is not None:
                    cleanup_plans.extend(
                        self._tracker_cleanup_plans(cycle=cycle, target=target)
                    )
        await session.flush()
        if session_ids is not None:
            residual_triggers = list(
                (
                    await session.scalars(
                        sa.select(RDBMailboxItem)
                        .where(
                            RDBMailboxItem.session_id.in_(session_ids),
                            RDBMailboxItem.kind
                            == MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                        )
                        .order_by(
                            RDBMailboxItem.session_id,
                            RDBMailboxItem.order_group,
                            RDBMailboxItem.order_sequence,
                            RDBMailboxItem.id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for trigger in residual_triggers:
                await session.delete(trigger)
                deleted_trigger_count += 1
            await session.flush()
        return ScheduledTaskLifecycleCleanup(
            deleted_task_count=0,
            deleted_admitted_cycle_count=deleted_cycle_count,
            deleted_trigger_count=deleted_trigger_count,
            preserved_started_cycle_count=preserved_started_cycle_count,
            cleanup_plans=tuple(cleanup_plans),
        )

    async def _binding_targets(
        self,
        session: AsyncSession,
        *,
        binding_ids: Sequence[str],
    ) -> dict[str, _BindingTarget]:
        unique_ids = sorted(set(binding_ids))
        if not unique_ids:
            return {}
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelConnection,
                    RDBAgentSession,
                    RDBAgent,
                    RDBWorkspace,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .outerjoin(RDBWorkspace, RDBWorkspace.id == RDBAgent.workspace_id)
                .where(
                    RDBExternalChannelBinding.id.in_(unique_ids),
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                )
            )
        ).all()
        return {
            binding.id: _BindingTarget(
                binding=binding,
                resource=resource,
                connection=connection,
                agent_session=agent_session,
                agent=agent,
                workspace=workspace,
            )
            for binding, resource, connection, agent_session, agent, workspace in rows
        }

    def _tracker_cleanup_plans(
        self,
        *,
        cycle: ScheduledTaskCycleState,
        target: _BindingTarget,
    ) -> list[ProviderEffectPlan]:
        plans: list[ProviderEffectPlan] = []
        for part in cycle.tracker_current_projection_parts:
            provider_message_key = part.provider_message_key
            if provider_message_key is None:
                continue
            plans.append(
                ProviderEffectPlan(
                    target=ProviderTarget(
                        operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                        binding_id=target.binding.id,
                        resource_id=target.resource.id,
                        connection_id=target.connection.id,
                        provider=target.connection.provider,
                        app_mode=target.connection.app_mode,
                        encrypted_credentials=target.connection.encrypted_credentials,
                        provider_tenant_id=target.connection.provider_tenant_id,
                        capabilities=target.connection.capabilities,
                        provider_configuration=(
                            decode_provider_connection_configuration(
                                target.connection.provider,
                                target.connection.provider_config,
                            )
                        ),
                        workspace_handle=(
                            None
                            if target.workspace is None
                            else target.workspace.handle
                        ),
                        agent_id=target.agent.id,
                        agent_session_id=target.agent_session.id,
                        agent_name=target.agent.name,
                        agent_avatar=target.agent.avatar,
                        request_payload={
                            "provider_message_key": provider_message_key,
                        },
                    ),
                    operation_key=ProviderOperationKey.from_seed(
                        f"scheduled-lifecycle-tracker-delete:{cycle.cycle_id}:"
                        f"{part.part_ordinal}"
                    ),
                )
            )
        return plans

    async def _lock_trigger(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        cycle_id: str,
    ) -> RDBMailboxItem | None:
        return await session.scalar(
            sa.select(RDBMailboxItem)
            .where(
                RDBMailboxItem.session_id == session_id,
                RDBMailboxItem.kind == MailboxItemKind.SCHEDULED_TASK_TRIGGER,
                RDBMailboxItem.idempotency_key == f"scheduled-task-trigger:{cycle_id}",
            )
            .with_for_update()
        )

    async def _lock_cycle_row(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> RDBToolkitState | None:
        return await session.scalar(
            sa.select(RDBToolkitState)
            .where(
                RDBToolkitState.agent_id == agent_id,
                RDBToolkitState.session_id == session_id,
                RDBToolkitState.toolkit_namespace == _NAMESPACE,
                RDBToolkitState.state_name == f"{_STATE_NAME_PREFIX}{cycle_id}",
            )
            .with_for_update()
        )

    async def _cycle(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskCycleState | None:
        row = await session.scalar(
            sa.select(RDBToolkitState).where(
                RDBToolkitState.agent_id == agent_id,
                RDBToolkitState.session_id == session_id,
                RDBToolkitState.toolkit_namespace == _NAMESPACE,
                RDBToolkitState.state_name == f"{_STATE_NAME_PREFIX}{cycle_id}",
            )
        )
        if row is None:
            return None
        return ScheduledTaskCycleState.model_validate(row.state_json)


__all__ = [
    "ScheduledTaskLifecycleCleanup",
    "ScheduledTaskLifecycleRepository",
    "ScheduledTaskLifecycleVerification",
]
