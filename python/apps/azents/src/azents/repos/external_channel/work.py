"""Persistence boundary for Channel Work and at-most-once delivery."""

import datetime
from collections.abc import Sequence
from typing import assert_never

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelActionMode,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelDeliveryTarget,
    ChannelWorkDelivery,
    ChannelWorkSnapshot,
    ChannelWorkTask,
)
from azents.services.external_channel.slack_events import (
    SLACK_MARKDOWN_TEXT_MAX_LENGTH,
)


class ExternalChannelWorkRepository:
    """Own Channel Work transitions and delivery ledger state."""

    async def ensure_active_work(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> None:
        """Create the one active Channel Work row for a newly invoked binding."""
        existing = await session.scalar(
            sa.select(RDBExternalChannelWork.id).where(
                RDBExternalChannelWork.binding_id == binding_id,
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
        )
        if existing is not None:
            return
        session.add(
            RDBExternalChannelWork(
                binding_id=binding_id,
                status=ExternalChannelWorkStatus.ACTIVE,
                schema_version=1,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress_payload=None,
                progress_provider_message_key=None,
                finished_at=None,
            )
        )
        await session.flush()

    async def has_active_binding(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
    ) -> bool:
        """Return whether the root Session can receive Channel Actions."""
        exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                    RDBExternalChannelBinding.agent_session_id == RDBAgentSession.id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelBinding.route_id
                    == RDBExternalChannelAgentRoute.id,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                    RDBExternalChannelConnection.status
                    == ExternalChannelConnectionStatus.ACTIVE,
                )
            )
        )
        return bool(exists)

    async def list_active_work(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        """List all active binding work in stable binding order."""
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelConnection,
                    RDBExternalChannelWork,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .join(
                    RDBAgent,
                    RDBAgent.id == RDBAgentSession.agent_id,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelWork,
                    sa.and_(
                        RDBExternalChannelWork.binding_id
                        == RDBExternalChannelBinding.id,
                        RDBExternalChannelWork.status
                        == ExternalChannelWorkStatus.ACTIVE,
                    ),
                )
                .where(
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelConnection.status
                    == ExternalChannelConnectionStatus.ACTIVE,
                )
                .order_by(RDBExternalChannelBinding.id)
            )
        ).all()
        snapshots: list[ChannelWorkSnapshot] = []
        for binding, resource, connection, work in rows:
            action = await session.scalar(
                sa.select(RDBExternalChannelAction)
                .where(RDBExternalChannelAction.work_id == work.id)
                .order_by(
                    RDBExternalChannelAction.created_at.desc(),
                    RDBExternalChannelAction.id.desc(),
                )
                .limit(1)
            )
            deliveries = await self._list_deliveries(
                session,
                channel_action_id=None if action is None else action.id,
            )
            latest_progress_delivery = await self._latest_progress_delivery(
                session,
                work_id=work.id,
            )
            snapshots.append(
                ChannelWorkSnapshot(
                    binding_id=binding.id,
                    provider=connection.provider,
                    resource_label=_resource_label(resource.labels, binding.id),
                    tasks=[ChannelWorkTask.model_validate(task) for task in work.tasks],
                    state_revision=work.state_revision,
                    desired_progress_revision=work.desired_progress_revision,
                    progress_provider_message_key=work.progress_provider_message_key,
                    projection_drift=_projection_drift(
                        work,
                        (
                            []
                            if latest_progress_delivery is None
                            else [latest_progress_delivery]
                        ),
                    ),
                    latest_action_mode=None if action is None else action.mode,
                    latest_deliveries=deliveries,
                )
            )
        return snapshots

    async def commit_action(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        now: datetime.datetime,
    ) -> ChannelActionCommit:
        """Commit work transition, action identity, and provider intents atomically."""
        requested_tasks = (
            [task.model_dump(mode="json") for task in tasks]
            if tasks is not None
            else None
        )
        request_payload: dict[str, object] = {
            "binding": binding_id,
            "mode": mode.value,
            **({"message": message} if message is not None else {}),
            **({"todo_update": requested_tasks} if requested_tasks is not None else {}),
        }
        existing = await session.scalar(
            sa.select(RDBExternalChannelAction).where(
                RDBExternalChannelAction.agent_session_id == session_id,
                RDBExternalChannelAction.client_tool_call_id == client_tool_call_id,
            )
        )
        if existing is not None:
            _validate_existing_action(existing, request_payload)
            return await self._build_commit(session, existing)

        session_row = await session.scalar(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .with_for_update()
        )
        if session_row is None:
            raise ValueError("AgentSession is not active.")
        existing = await session.scalar(
            sa.select(RDBExternalChannelAction).where(
                RDBExternalChannelAction.agent_session_id == session_id,
                RDBExternalChannelAction.client_tool_call_id == client_tool_call_id,
            )
        )
        if existing is not None:
            _validate_existing_action(existing, request_payload)
            return await self._build_commit(session, existing)
        agent = await session.scalar(
            sa.select(RDBAgent).where(
                RDBAgent.id == agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
        )
        if agent is None:
            raise ValueError("Agent is not active.")
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == session_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        if binding is None:
            raise ValueError("External Channel binding is not active.")
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute).where(
                RDBExternalChannelAgentRoute.id == binding.route_id,
                RDBExternalChannelAgentRoute.agent_id == agent_id,
            )
        )
        if route is None:
            raise ValueError("External Channel route is not active.")
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.id == route.connection_id,
                RDBExternalChannelConnection.status
                == ExternalChannelConnectionStatus.ACTIVE,
            )
        )
        if connection is None:
            raise ValueError("External Channel connection is not active.")
        _validate_message_length(connection.provider, message)
        resource = await session.get(RDBExternalChannelResource, binding.resource_id)
        if resource is None:
            raise ValueError("External Channel resource is unavailable.")

        work = await session.scalar(
            sa.select(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.binding_id == binding.id,
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
            .with_for_update()
        )
        if work is None:
            work = RDBExternalChannelWork(
                binding_id=binding.id,
                status=ExternalChannelWorkStatus.ACTIVE,
                schema_version=1,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress_payload=None,
                progress_provider_message_key=None,
                finished_at=None,
            )
            session.add(work)
            await session.flush()

        next_tasks = (
            requested_tasks if requested_tasks is not None else list(work.tasks)
        )
        operations: list[
            tuple[ExternalChannelDeliveryOperation, dict[str, object]]
        ] = []
        if message is not None:
            operations.append(
                (
                    ExternalChannelDeliveryOperation.REPLY,
                    _provider_payload(resource.labels, text=message),
                )
            )
        if mode is ExternalChannelActionMode.CONTINUE:
            validated_tasks = [
                ChannelWorkTask.model_validate(task) for task in next_tasks
            ]
            if not any(
                task.status is not ExternalChannelWorkTaskStatus.COMPLETED
                for task in validated_tasks
            ):
                raise ValueError(
                    "Continue must leave at least one unfinished Channel Work task."
                )
            work.tasks = next_tasks
            work.state_revision += 1
            if tasks is not None:
                work.desired_progress_revision += 1
                work.desired_progress_payload = {"tasks": next_tasks}
                operations.append(
                    (
                        ExternalChannelDeliveryOperation.PROGRESS_CREATE
                        if work.progress_provider_message_key is None
                        else ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                        _provider_payload(
                            resource.labels,
                            text=_render_progress(tasks),
                            blocks=_render_progress_blocks(tasks),
                            provider_message_key=work.progress_provider_message_key,
                            desired_progress_revision=work.desired_progress_revision,
                        ),
                    )
                )
        else:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.state_revision += 1
            work.finished_at = now
            work.desired_progress_revision += 1
            work.desired_progress_payload = None
            if work.progress_provider_message_key is not None:
                operations.append(
                    (
                        ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                        _provider_payload(
                            resource.labels,
                            provider_message_key=work.progress_provider_message_key,
                            desired_progress_revision=work.desired_progress_revision,
                        ),
                    )
                )

        action = RDBExternalChannelAction(
            agent_session_id=session_id,
            agent_run_id=run_id,
            client_tool_call_id=client_tool_call_id,
            binding_id=binding.id,
            mode=mode,
            state_revision=work.state_revision,
            request_payload=request_payload,
            work_id=work.id,
            completed_at=None,
        )
        session.add(action)
        await session.flush()
        for operation, payload in operations:
            session.add(
                RDBExternalChannelDeliveryAttempt(
                    origin_type=ExternalChannelDeliveryOriginType.CHANNEL_ACTION,
                    origin_id=action.id,
                    operation=operation,
                    request_payload=payload,
                    status=ExternalChannelDeliveryStatus.PENDING,
                    channel_action_id=action.id,
                    binding_id=binding.id,
                    provider_message_key=(
                        work.progress_provider_message_key
                        if operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                        else None
                    ),
                    error_kind=None,
                    error_summary=None,
                    attempted_at=None,
                    completed_at=None,
                )
            )
        await session.flush()
        return await self._build_commit(session, action)

    async def get_delivery_target(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        """Load provider target and encrypted credentials for one intent."""
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelDeliveryAttempt,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                )
                .join(
                    RDBExternalChannelBinding,
                    RDBExternalChannelBinding.id
                    == RDBExternalChannelDeliveryAttempt.binding_id,
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
                .where(RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id)
            )
        ).one_or_none()
        if row is None:
            return None
        attempt, route, connection = row
        if attempt.binding_id is None:
            return None
        return ChannelDeliveryTarget(
            delivery_attempt_id=attempt.id,
            operation=attempt.operation,
            status=attempt.status,
            binding_id=attempt.binding_id,
            connection_id=route.connection_id,
            provider=connection.provider,
            encrypted_credentials=connection.encrypted_credentials,
            provider_tenant_id=connection.provider_tenant_id,
            request_payload=dict(attempt.request_payload),
        )

    async def start_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Cross the sole provider-attempt boundary."""
        result = await session.execute(
            sa.update(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.PENDING,
            )
            .values(
                status=ExternalChannelDeliveryStatus.ATTEMPTING,
                attempted_at=now,
            )
            .returning(RDBExternalChannelDeliveryAttempt.id)
        )
        return result.scalar_one_or_none() is not None

    async def finish_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        status: ExternalChannelDeliveryStatus,
        provider_message_key: str | None,
        error_kind: str | None,
        error_summary: str | None,
        now: datetime.datetime,
    ) -> None:
        """Persist a terminal delivery outcome and progress identity."""
        attempt = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.ATTEMPTING,
            )
            .with_for_update()
        )
        if attempt is None:
            return
        attempt.status = status
        if provider_message_key is not None:
            attempt.provider_message_key = provider_message_key
        attempt.error_kind = error_kind
        attempt.error_summary = error_summary
        attempt.completed_at = now
        if (
            attempt.binding_id is not None
            and status is ExternalChannelDeliveryStatus.DELIVERED
        ):
            work = await session.scalar(
                sa.select(RDBExternalChannelWork)
                .where(RDBExternalChannelWork.binding_id == attempt.binding_id)
                .order_by(RDBExternalChannelWork.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if work is not None:
                if (
                    attempt.operation
                    is ExternalChannelDeliveryOperation.PROGRESS_CREATE
                ):
                    work.progress_provider_message_key = provider_message_key
                elif (
                    attempt.operation
                    is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                ):
                    work.progress_provider_message_key = None
        await session.flush()

    async def complete_action(
        self,
        session: AsyncSession,
        *,
        action_id: str,
        now: datetime.datetime,
    ) -> ChannelActionCommit:
        """Mark an action complete after all its intents become terminal."""
        action = await session.scalar(
            sa.select(RDBExternalChannelAction)
            .where(RDBExternalChannelAction.id == action_id)
            .with_for_update()
        )
        if action is None:
            raise RuntimeError("External Channel action disappeared.")
        action.completed_at = now
        await session.flush()
        return await self._build_commit(session, action)

    async def recover_action_by_client_tool_call(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        client_tool_call_id: str,
        now: datetime.datetime,
    ) -> ChannelActionCommit | None:
        """Recover committed action outcomes without provider re-execution."""
        action = await session.scalar(
            sa.select(RDBExternalChannelAction)
            .where(
                RDBExternalChannelAction.agent_session_id == session_id,
                RDBExternalChannelAction.client_tool_call_id == client_tool_call_id,
            )
            .with_for_update()
        )
        if action is None:
            return None
        attempts = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDeliveryAttempt)
                    .where(
                        RDBExternalChannelDeliveryAttempt.channel_action_id
                        == action.id,
                        RDBExternalChannelDeliveryAttempt.status.in_(
                            (
                                ExternalChannelDeliveryStatus.PENDING,
                                ExternalChannelDeliveryStatus.ATTEMPTING,
                            )
                        ),
                    )
                    .order_by(RDBExternalChannelDeliveryAttempt.id)
                    .with_for_update()
                )
            ).all()
        )
        for attempt in attempts:
            if attempt.status is ExternalChannelDeliveryStatus.PENDING:
                attempt.status = ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                attempt.error_kind = "recovered_not_attempted"
                attempt.error_summary = (
                    "The provider operation did not begin before recovery."
                )
            else:
                attempt.status = ExternalChannelDeliveryStatus.UNKNOWN
                attempt.error_kind = "recovered_outcome_unknown"
                attempt.error_summary = (
                    "The provider operation began but its outcome is unknown."
                )
            attempt.completed_at = now
        action.completed_at = now
        await session.flush()
        return await self._build_commit(session, action)

    async def list_recoverable_deliveries(
        self,
        session: AsyncSession,
        *,
        channel_action_id: str | None,
    ) -> list[ChannelWorkDelivery]:
        """Terminalize pending and attempting rows without provider execution."""
        predicate = (
            RDBExternalChannelDeliveryAttempt.channel_action_id == channel_action_id
            if channel_action_id is not None
            else RDBExternalChannelDeliveryAttempt.origin_type
            == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT
        )
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDeliveryAttempt)
                    .where(
                        predicate,
                        RDBExternalChannelDeliveryAttempt.status.in_(
                            (
                                ExternalChannelDeliveryStatus.PENDING,
                                ExternalChannelDeliveryStatus.ATTEMPTING,
                            )
                        ),
                    )
                    .order_by(RDBExternalChannelDeliveryAttempt.id)
                    .with_for_update()
                )
            ).all()
        )
        now = datetime.datetime.now(datetime.UTC)
        for row in rows:
            if row.status is ExternalChannelDeliveryStatus.PENDING:
                row.status = ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                row.error_kind = "recovered_not_attempted"
                row.error_summary = (
                    "The provider operation did not begin before recovery."
                )
            else:
                row.status = ExternalChannelDeliveryStatus.UNKNOWN
                row.error_kind = "recovered_outcome_unknown"
                row.error_summary = (
                    "The provider operation began but its outcome is unknown."
                )
            row.completed_at = now
        await session.flush()
        if channel_action_id is None:
            return [_delivery(row) for row in rows]
        action = await session.get(RDBExternalChannelAction, channel_action_id)
        if action is not None:
            action.completed_at = now
        return await self._list_deliveries(
            session,
            channel_action_id=channel_action_id,
        )

    async def recover_archive_cleanup(
        self,
        session: AsyncSession,
        *,
        current_delivery_ids: Sequence[str],
        now: datetime.datetime,
    ) -> None:
        """Terminalize prior archive cleanup without provider re-execution."""
        predicate = [
            RDBExternalChannelDeliveryAttempt.origin_type
            == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
            RDBExternalChannelDeliveryAttempt.status.in_(
                (
                    ExternalChannelDeliveryStatus.PENDING,
                    ExternalChannelDeliveryStatus.ATTEMPTING,
                )
            ),
        ]
        if current_delivery_ids:
            predicate.append(
                RDBExternalChannelDeliveryAttempt.id.not_in(current_delivery_ids)
            )
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDeliveryAttempt)
                    .where(*predicate)
                    .order_by(RDBExternalChannelDeliveryAttempt.id)
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            if row.status is ExternalChannelDeliveryStatus.PENDING:
                row.status = ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                row.error_kind = "recovered_not_attempted"
                row.error_summary = "Archive cleanup did not begin before recovery."
            else:
                row.status = ExternalChannelDeliveryStatus.UNKNOWN
                row.error_kind = "recovered_outcome_unknown"
                row.error_summary = "Archive cleanup began but its outcome is unknown."
            row.completed_at = now
        await session.flush()

    async def list_archive_cleanup_ids(
        self,
        session: AsyncSession,
        *,
        delivery_ids: Sequence[str],
    ) -> list[str]:
        """Return only current archive intents that remain pending."""
        if not delivery_ids:
            return []
        result = await session.scalars(
            sa.select(RDBExternalChannelDeliveryAttempt.id)
            .where(
                RDBExternalChannelDeliveryAttempt.id.in_(delivery_ids),
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.PENDING,
            )
            .order_by(RDBExternalChannelDeliveryAttempt.created_at)
        )
        return list(result)

    async def _build_commit(
        self,
        session: AsyncSession,
        action: RDBExternalChannelAction,
    ) -> ChannelActionCommit:
        work = await session.get(RDBExternalChannelWork, action.work_id)
        if work is None:
            raise RuntimeError("External Channel work disappeared.")
        return ChannelActionCommit(
            action_id=action.id,
            binding_id=action.binding_id,
            work_id=work.id,
            work_status=work.status,
            state_revision=work.state_revision,
            deliveries=await self._list_deliveries(
                session,
                channel_action_id=action.id,
            ),
        )

    async def _list_deliveries(
        self,
        session: AsyncSession,
        *,
        channel_action_id: str | None,
    ) -> list[ChannelWorkDelivery]:
        if channel_action_id is None:
            return []
        rows = await session.scalars(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.channel_action_id == channel_action_id
            )
            .order_by(
                RDBExternalChannelDeliveryAttempt.created_at,
                RDBExternalChannelDeliveryAttempt.id,
            )
        )
        return [_delivery(row) for row in rows]

    async def _latest_progress_delivery(
        self,
        session: AsyncSession,
        *,
        work_id: str,
    ) -> ChannelWorkDelivery | None:
        row = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .join(
                RDBExternalChannelAction,
                RDBExternalChannelAction.id
                == RDBExternalChannelDeliveryAttempt.channel_action_id,
            )
            .where(
                RDBExternalChannelAction.work_id == work_id,
                RDBExternalChannelDeliveryAttempt.operation.in_(
                    (
                        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                        ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                        ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    )
                ),
            )
            .order_by(
                RDBExternalChannelDeliveryAttempt.created_at.desc(),
                RDBExternalChannelDeliveryAttempt.id.desc(),
            )
            .limit(1)
        )
        return None if row is None else _delivery(row)


def _delivery(row: RDBExternalChannelDeliveryAttempt) -> ChannelWorkDelivery:
    """Project one safe delivery result."""
    return ChannelWorkDelivery(
        id=row.id,
        operation=row.operation,
        status=row.status,
        provider_message_key=row.provider_message_key,
        error_kind=row.error_kind,
        error_summary=row.error_summary,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _validate_existing_action(
    action: RDBExternalChannelAction,
    request_payload: dict[str, object],
) -> None:
    """Reject reuse of one durable tool-call identity with different input."""
    if action.request_payload != request_payload:
        raise ValueError("Client tool call identity conflicts with an action.")


def _provider_payload(
    labels: dict[str, object] | None,
    *,
    text: str | None = None,
    blocks: list[dict[str, object]] | None = None,
    provider_message_key: str | None = None,
    desired_progress_revision: int | None = None,
) -> dict[str, object]:
    """Build one persisted provider request intent without credentials."""
    labels = labels or {}
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("External Channel resource has no provider channel.")
    if not isinstance(thread_ts, str) or not thread_ts:
        raise ValueError("External Channel resource has no provider thread.")
    payload: dict[str, object] = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }
    if text is not None:
        payload["text"] = text
    if blocks is not None:
        payload["blocks"] = blocks
    if provider_message_key is not None:
        payload["provider_message_key"] = provider_message_key
    if desired_progress_revision is not None:
        payload["desired_progress_revision"] = desired_progress_revision
    return payload


def _render_progress(tasks: Sequence[ChannelWorkTask]) -> str:
    """Render a deterministic provider progress message."""
    lines = ["Agent progress"]
    for task in tasks:
        marker = {
            "pending": "○",
            "in_progress": "◐",
            "completed": "●",
        }[task.status.value]
        lines.append(f"{marker} {task.title}")
    return "\n".join(lines)


def _render_progress_blocks(
    tasks: Sequence[ChannelWorkTask],
) -> list[dict[str, object]]:
    """Render deterministic accessible Slack Block Kit task progress."""
    lines = [f"{_task_marker(task.status)} {task.title}" for task in tasks]
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Agent progress"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]


def _task_marker(status: ExternalChannelWorkTaskStatus) -> str:
    """Return the Slack display marker for one Channel Work state."""
    return {
        ExternalChannelWorkTaskStatus.PENDING: "○",
        ExternalChannelWorkTaskStatus.IN_PROGRESS: "◐",
        ExternalChannelWorkTaskStatus.COMPLETED: "●",
    }[status]


def _validate_message_length(
    provider: ExternalChannelProvider,
    message: str | None,
) -> None:
    """Validate one provider-bound conversational message before commit."""
    if message is None:
        return
    match provider:
        case ExternalChannelProvider.SLACK:
            maximum = SLACK_MARKDOWN_TEXT_MAX_LENGTH
        case _ as unreachable:
            assert_never(unreachable)
    if len(message) > maximum:
        raise ValueError(
            f"External Channel message exceeds the {maximum}-character provider limit."
        )


def _resource_label(labels: dict[str, object] | None, fallback: str) -> str:
    """Return a safe resource label for model context."""
    labels = labels or {}
    for key in ("display_name", "channel_name", "label", "channel_id"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _projection_drift(
    work: RDBExternalChannelWork,
    deliveries: Sequence[ChannelWorkDelivery],
) -> str:
    """Derive a bounded progress projection drift label."""
    progress = [
        item
        for item in deliveries
        if item.operation
        in {
            ExternalChannelDeliveryOperation.PROGRESS_CREATE,
            ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
            ExternalChannelDeliveryOperation.PROGRESS_DELETE,
        }
    ]
    if progress and progress[-1].status is ExternalChannelDeliveryStatus.UNKNOWN:
        return "unknown"
    if progress and progress[-1].status in {
        ExternalChannelDeliveryStatus.FAILED,
        ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
    }:
        return (
            "delete_failed"
            if progress[-1].operation
            is ExternalChannelDeliveryOperation.PROGRESS_DELETE
            else "stale"
        )
    if work.desired_progress_payload is not None:
        return (
            "missing" if work.progress_provider_message_key is None else "synchronized"
        )
    return "none" if work.progress_provider_message_key is None else "stale"
