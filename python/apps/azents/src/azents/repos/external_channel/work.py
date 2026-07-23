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
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
)
from azents.core.slack_external_channel_progress import (
    SlackProgressPresentation,
    render_slack_persisted_progress,
    render_slack_progress,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessRequest,
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
    ExternalChannelFileAccessTarget,
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
                schema_version=2,
                title=None,
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

    async def get_active_file_access_target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> ExternalChannelFileAccessTarget | None:
        """Resolve one active binding and its current provider credential boundary."""
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelConnection,
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
                .where(
                    RDBExternalChannelBinding.id == binding_id,
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                    RDBExternalChannelBinding.activation_status
                    == ExternalChannelBindingActivationStatus.ACTIVE,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelResource.status
                    == ExternalChannelResourceStatus.ACTIVE,
                    RDBExternalChannelResource.connection_id
                    == RDBExternalChannelConnection.id,
                    RDBExternalChannelConnection.status
                    == ExternalChannelConnectionStatus.ACTIVE,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        binding, connection = row
        return ExternalChannelFileAccessTarget(
            binding_id=binding.id,
            connection_id=connection.id,
            provider=connection.provider,
            encrypted_credentials=connection.encrypted_credentials,
            capabilities=connection.capabilities,
        )

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
                    title=work.title,
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
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
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
            **({"title": title} if title is not None else {}),
            **({"todo_update": requested_tasks} if requested_tasks is not None else {}),
            **(
                {"files": [item.model_dump(mode="json") for item in files]}
                if files
                else {}
            ),
        }
        if mode is ExternalChannelActionMode.FINISH and message is None:
            raise ValueError("Finish requires a final External Channel reply.")
        if files and message is None:
            raise ValueError("Channel file publication requires a message.")
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
        created_work = work is None
        if created_work:
            work = RDBExternalChannelWork(
                binding_id=binding.id,
                status=ExternalChannelWorkStatus.ACTIVE,
                schema_version=2,
                title=None,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress_payload=None,
                progress_provider_message_key=None,
                finished_at=None,
            )
            session.add(work)
            await session.flush()

        operations: list[
            tuple[ExternalChannelDeliveryOperation, dict[str, object]]
        ] = []
        if message is not None:
            operations.append(
                (
                    ExternalChannelDeliveryOperation.REPLY,
                    _provider_payload(resource.labels, text=message, files=files),
                )
            )
        if mode is ExternalChannelActionMode.CONTINUE:
            progress_changed = title is not None or requested_tasks is not None
            if requested_tasks is not None and title is None:
                raise ValueError("A Channel Work task update requires a work title.")
            if title is not None and not title.endswith(("…", "...")):
                raise ValueError("Channel Work titles must end with an ellipsis.")
            if title is not None and requested_tasks is None and not work.tasks:
                raise ValueError("A title-only update requires existing Channel Work.")
            if progress_changed:
                next_tasks = (
                    requested_tasks if requested_tasks is not None else list(work.tasks)
                )
                validated_tasks = [
                    ChannelWorkTask.model_validate(task) for task in next_tasks
                ]
                if not validated_tasks:
                    raise ValueError("Working Channel Work requires at least one task.")
                if not any(
                    task.status
                    not in {
                        ExternalChannelWorkTaskStatus.COMPLETED,
                        ExternalChannelWorkTaskStatus.FAILED,
                    }
                    for task in validated_tasks
                ):
                    raise ValueError(
                        "Continue must leave at least one unfinished Channel Work task."
                    )
                next_title = title if title is not None else work.title
                if next_title is None:
                    raise ValueError("Working Channel Work requires a title.")
                progress = ExternalChannelDesiredProgress(
                    schema_version=2,
                    state="working",
                    title=next_title,
                    tasks=validated_tasks,
                )
                work.title = next_title
                work.tasks = [task.model_dump(mode="json") for task in validated_tasks]
                work.state_revision += 1
                work.desired_progress_revision += 1
                work.desired_progress_payload = progress.model_dump(mode="json")
                presentation = _render_progress(
                    connection.provider,
                    progress,
                    work_id=work.id,
                    desired_progress_revision=work.desired_progress_revision,
                )
                if created_work:
                    operations.append(
                        (
                            ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                            _provider_payload(
                                resource.labels,
                                text=presentation.text,
                                blocks=presentation.blocks,
                                desired_progress_revision=(
                                    work.desired_progress_revision
                                ),
                            ),
                        )
                    )
                elif work.progress_provider_message_key is not None:
                    operations.append(
                        (
                            ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                            _provider_payload(
                                resource.labels,
                                text=presentation.text,
                                blocks=presentation.blocks,
                                provider_message_key=(
                                    work.progress_provider_message_key
                                ),
                                desired_progress_revision=(
                                    work.desired_progress_revision
                                ),
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
                            desired_progress_revision=(work.desired_progress_revision),
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
                        if operation
                        in {
                            ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                            ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                        }
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

    async def find_action_by_client_tool_call(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        client_tool_call_id: str,
    ) -> tuple[ChannelActionCommit, dict[str, object]] | None:
        """Return one already committed action before any Runtime preflight."""
        action = await session.scalar(
            sa.select(RDBExternalChannelAction).where(
                RDBExternalChannelAction.agent_session_id == session_id,
                RDBExternalChannelAction.client_tool_call_id == client_tool_call_id,
            )
        )
        if action is None:
            return None
        return (
            await self._build_commit(session, action),
            dict(action.request_payload),
        )

    async def get_delivery_target(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        """Load provider target and encrypted credentials for one intent."""
        attempt = await session.get(
            RDBExternalChannelDeliveryAttempt,
            delivery_attempt_id,
        )
        if attempt is None:
            return None
        if attempt.binding_id is None:
            if (
                attempt.origin_type
                is not ExternalChannelDeliveryOriginType.ACCESS_REQUEST
            ):
                return None
            request_route = (
                await session.execute(
                    sa.select(
                        RDBExternalChannelAgentRoute,
                        RDBExternalChannelConnection,
                    )
                    .join(
                        RDBExternalChannelAccessRequest,
                        RDBExternalChannelAccessRequest.route_id
                        == RDBExternalChannelAgentRoute.id,
                    )
                    .join(
                        RDBExternalChannelConnection,
                        RDBExternalChannelConnection.id
                        == RDBExternalChannelAgentRoute.connection_id,
                    )
                    .where(RDBExternalChannelAccessRequest.id == attempt.origin_id)
                )
            ).one_or_none()
            if request_route is None:
                return None
            route, connection = request_route
            return ChannelDeliveryTarget(
                delivery_attempt_id=attempt.id,
                operation=attempt.operation,
                status=attempt.status,
                binding_id=None,
                connection_id=route.connection_id,
                provider=connection.provider,
                encrypted_credentials=connection.encrypted_credentials,
                provider_tenant_id=connection.provider_tenant_id,
                request_payload=dict(attempt.request_payload),
            )
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

    async def skip_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Terminalize one provider intent whose prerequisite did not complete."""
        result = await session.execute(
            sa.update(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.PENDING,
            )
            .values(
                status=ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
                error_kind=error_kind,
                error_summary=error_summary,
                completed_at=now,
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
    ) -> str | None:
        """Persist an outcome and return a missing-Tracker recovery intent."""
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
            return None
        attempt.status = status
        if provider_message_key is not None:
            attempt.provider_message_key = provider_message_key
        attempt.error_kind = error_kind
        attempt.error_summary = error_summary
        attempt.completed_at = now
        work = await self._work_for_delivery_attempt(session, attempt=attempt)
        effective_status = status
        if (
            work is not None
            and attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE
            and status is ExternalChannelDeliveryStatus.FAILED
            and error_kind == "message_not_found"
        ):
            effective_status = ExternalChannelDeliveryStatus.DELIVERED
            attempt.status = effective_status
            attempt.error_kind = "message_already_absent"
            attempt.error_summary = (
                "Slack already removed the Activity Tracker message."
            )
        if (
            work is not None
            and effective_status is ExternalChannelDeliveryStatus.DELIVERED
        ):
            if attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE:
                work.progress_provider_message_key = provider_message_key
            elif attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                work.progress_provider_message_key = None
        recovery_id = None
        if (
            work is not None
            and attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE
            and effective_status is ExternalChannelDeliveryStatus.DELIVERED
            and provider_message_key is not None
        ):
            attempted_revision = attempt.request_payload.get(
                "desired_progress_revision"
            )
            if (
                work.status is ExternalChannelWorkStatus.ACTIVE
                and work.desired_progress_payload is not None
                and isinstance(attempted_revision, int)
                and work.desired_progress_revision > attempted_revision
            ):
                presentation = _render_persisted_progress(
                    ExternalChannelProvider.SLACK,
                    work.desired_progress_payload,
                    work_id=work.id,
                    desired_progress_revision=work.desired_progress_revision,
                )
                existing_catchup = await session.scalar(
                    sa.select(RDBExternalChannelDeliveryAttempt).where(
                        RDBExternalChannelDeliveryAttempt.origin_type
                        == ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                        RDBExternalChannelDeliveryAttempt.origin_id == attempt.id,
                        RDBExternalChannelDeliveryAttempt.binding_id
                        == attempt.binding_id,
                        RDBExternalChannelDeliveryAttempt.operation
                        == ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                    )
                )
                if existing_catchup is None:
                    catchup_payload = dict(attempt.request_payload)
                    catchup_payload.update(
                        {
                            "work_id": work.id,
                            "text": presentation.text,
                            "blocks": presentation.blocks,
                            "provider_message_key": provider_message_key,
                            "desired_progress_revision": (
                                work.desired_progress_revision
                            ),
                        }
                    )
                    existing_catchup = RDBExternalChannelDeliveryAttempt(
                        origin_type=(
                            ExternalChannelDeliveryOriginType.MANAGER_OPERATION
                        ),
                        origin_id=attempt.id,
                        operation=ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                        request_payload=catchup_payload,
                        status=ExternalChannelDeliveryStatus.PENDING,
                        channel_action_id=attempt.channel_action_id,
                        binding_id=attempt.binding_id,
                        provider_message_key=provider_message_key,
                        error_kind=None,
                        error_summary=None,
                        attempted_at=None,
                        completed_at=None,
                    )
                    session.add(existing_catchup)
                await session.flush()
                if existing_catchup.status is ExternalChannelDeliveryStatus.PENDING:
                    recovery_id = existing_catchup.id
            elif work.status is ExternalChannelWorkStatus.FINISHED:
                recovery_id = await self._ensure_finished_tracker_delete(
                    session,
                    work=work,
                )
        if (
            work is not None
            and work.status is ExternalChannelWorkStatus.ACTIVE
            and work.desired_progress_payload is not None
            and attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE
            and effective_status is ExternalChannelDeliveryStatus.FAILED
            and error_kind == "message_not_found"
        ):
            target_key = attempt.request_payload.get("provider_message_key")
            if (
                isinstance(target_key, str)
                and work.progress_provider_message_key == target_key
            ):
                work.progress_provider_message_key = None
                existing_recovery = await session.scalar(
                    sa.select(RDBExternalChannelDeliveryAttempt).where(
                        RDBExternalChannelDeliveryAttempt.origin_type
                        == attempt.origin_type,
                        RDBExternalChannelDeliveryAttempt.origin_id
                        == attempt.origin_id,
                        RDBExternalChannelDeliveryAttempt.binding_id
                        == attempt.binding_id,
                        RDBExternalChannelDeliveryAttempt.operation
                        == ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    )
                )
                if existing_recovery is None:
                    recovery_payload = dict(attempt.request_payload)
                    recovery_payload.pop("provider_message_key", None)
                    recovery_payload["work_id"] = work.id
                    recovery_payload["replaces_provider_message_key"] = target_key
                    existing_recovery = RDBExternalChannelDeliveryAttempt(
                        origin_type=attempt.origin_type,
                        origin_id=attempt.origin_id,
                        operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                        request_payload=recovery_payload,
                        status=ExternalChannelDeliveryStatus.PENDING,
                        channel_action_id=attempt.channel_action_id,
                        binding_id=attempt.binding_id,
                        provider_message_key=None,
                        error_kind=None,
                        error_summary=None,
                        attempted_at=None,
                        completed_at=None,
                    )
                    session.add(existing_recovery)
                await session.flush()
                if existing_recovery.status is ExternalChannelDeliveryStatus.PENDING:
                    recovery_id = existing_recovery.id
        if (
            work is not None
            and work.status is ExternalChannelWorkStatus.FINISHED
            and attempt.operation is ExternalChannelDeliveryOperation.REPLY
            and effective_status is ExternalChannelDeliveryStatus.DELIVERED
        ):
            cleanup_id = await self._ensure_finished_tracker_delete(
                session,
                work=work,
            )
            if cleanup_id is not None:
                recovery_id = cleanup_id
        await session.flush()
        return recovery_id

    async def _ensure_finished_tracker_delete(
        self,
        session: AsyncSession,
        *,
        work: RDBExternalChannelWork,
    ) -> str | None:
        """Create one cleanup intent after both Tracker creation and reply delivery."""
        provider_message_key = work.progress_provider_message_key
        if (
            work.status is not ExternalChannelWorkStatus.FINISHED
            or provider_message_key is None
        ):
            return None
        finish_action = await session.scalar(
            sa.select(RDBExternalChannelAction)
            .where(
                RDBExternalChannelAction.work_id == work.id,
                RDBExternalChannelAction.mode == ExternalChannelActionMode.FINISH,
            )
            .order_by(
                RDBExternalChannelAction.created_at.desc(),
                RDBExternalChannelAction.id.desc(),
            )
        )
        if finish_action is None:
            return None
        reply = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt).where(
                RDBExternalChannelDeliveryAttempt.channel_action_id == finish_action.id,
                RDBExternalChannelDeliveryAttempt.operation
                == ExternalChannelDeliveryOperation.REPLY,
            )
        )
        if reply is None or reply.status is not ExternalChannelDeliveryStatus.DELIVERED:
            return None
        cleanup = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt).where(
                RDBExternalChannelDeliveryAttempt.channel_action_id == finish_action.id,
                RDBExternalChannelDeliveryAttempt.operation
                == ExternalChannelDeliveryOperation.PROGRESS_DELETE,
            )
        )
        if cleanup is None:
            cleanup_payload = dict(reply.request_payload)
            cleanup_payload.pop("text", None)
            cleanup_payload.update(
                {
                    "provider_message_key": provider_message_key,
                    "desired_progress_revision": work.desired_progress_revision,
                }
            )
            cleanup = RDBExternalChannelDeliveryAttempt(
                origin_type=ExternalChannelDeliveryOriginType.CHANNEL_ACTION,
                origin_id=finish_action.id,
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                request_payload=cleanup_payload,
                status=ExternalChannelDeliveryStatus.PENDING,
                channel_action_id=finish_action.id,
                binding_id=finish_action.binding_id,
                provider_message_key=provider_message_key,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            )
            session.add(cleanup)
            await session.flush()
        if cleanup.status is ExternalChannelDeliveryStatus.PENDING:
            return cleanup.id
        return None

    async def _work_for_delivery_attempt(
        self,
        session: AsyncSession,
        *,
        attempt: RDBExternalChannelDeliveryAttempt,
    ) -> RDBExternalChannelWork | None:
        """Lock the work cycle explicitly owned by one delivery attempt."""
        if attempt.channel_action_id is not None:
            work_id = await session.scalar(
                sa.select(RDBExternalChannelAction.work_id).where(
                    RDBExternalChannelAction.id == attempt.channel_action_id
                )
            )
        else:
            raw_work_id = attempt.request_payload.get("work_id")
            work_id = raw_work_id if isinstance(raw_work_id, str) else None
        if work_id is None:
            return None
        return await session.scalar(
            sa.select(RDBExternalChannelWork)
            .where(RDBExternalChannelWork.id == work_id)
            .with_for_update()
        )

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
                sa.case(
                    (
                        RDBExternalChannelDeliveryAttempt.operation
                        == ExternalChannelDeliveryOperation.REPLY,
                        0,
                    ),
                    else_=1,
                ),
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
            .outerjoin(
                RDBExternalChannelAction,
                RDBExternalChannelAction.id
                == RDBExternalChannelDeliveryAttempt.channel_action_id,
            )
            .where(
                sa.or_(
                    RDBExternalChannelAction.work_id == work_id,
                    sa.and_(
                        RDBExternalChannelDeliveryAttempt.channel_action_id.is_(None),
                        RDBExternalChannelDeliveryAttempt.origin_id == work_id,
                    ),
                ),
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
    files: Sequence[ExternalChannelOutboundFileManifest] = (),
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
    if files:
        payload["files"] = [item.model_dump(mode="json") for item in files]
    if blocks is not None:
        payload["blocks"] = blocks
    if provider_message_key is not None:
        payload["provider_message_key"] = provider_message_key
    if desired_progress_revision is not None:
        payload["desired_progress_revision"] = desired_progress_revision
    return payload


def _render_progress(
    provider: ExternalChannelProvider,
    progress: ExternalChannelDesiredProgress,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> SlackProgressPresentation:
    """Lower canonical progress through the active provider adapter."""
    match provider:
        case ExternalChannelProvider.SLACK:
            return render_slack_progress(
                progress,
                work_id=work_id,
                desired_progress_revision=desired_progress_revision,
            )
        case _ as unreachable:
            assert_never(unreachable)


def _render_persisted_progress(
    provider: ExternalChannelProvider,
    payload: object,
    *,
    work_id: str,
    desired_progress_revision: int,
) -> SlackProgressPresentation:
    """Validate and lower one durable canonical progress snapshot."""
    match provider:
        case ExternalChannelProvider.SLACK:
            return render_slack_persisted_progress(
                payload,
                work_id=work_id,
                desired_progress_revision=desired_progress_revision,
            )
        case _ as unreachable:
            assert_never(unreachable)


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
