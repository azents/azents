"""External Channel access decisions and binding activation setup."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionWakeUp
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelResourceStatus,
    InputBufferKind,
    InputBufferSchedulingMode,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrant,
    ExternalChannelAccessGrantCreate,
    ExternalChannelAccessRequest,
    ExternalChannelBinding,
    ExternalChannelBindingCreate,
    ExternalChannelBlock,
    ExternalChannelBlockCreate,
    ExternalChannelInvocationBatchCreate,
    ExternalChannelInvocationBatchItemCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.input_buffer import (
    EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY,
    InputBufferEnqueue,
    InputBufferService,
)
from azents.worker.session.lifecycle import SessionLifecycleService


class ExternalChannelAccessDecisionError(ValueError):
    """An access decision cannot be applied to the current domain state."""


class ExternalChannelAccessRequestNotFound(LookupError):
    """The access request does not exist."""


@dataclass(frozen=True)
class ExternalChannelAllowedAccess:
    """Durable result of an idempotent Allow decision."""

    request: ExternalChannelAccessRequest
    binding: ExternalChannelBinding
    grant: ExternalChannelAccessGrant
    control_delete_delivery_id: str | None


@dataclass(frozen=True)
class ExternalChannelResolvedAccess:
    """Durable result of an idempotent Deny or Block decision."""

    request: ExternalChannelAccessRequest
    control_delete_delivery_id: str | None


@dataclass(frozen=True)
class ExternalChannelRevokedAccess:
    """Durable access-policy revocation result."""

    grant: ExternalChannelAccessGrant


@dataclass(frozen=True)
class ExternalChannelRemovedBlock:
    """Durable block-removal result."""

    block: ExternalChannelBlock


@dataclass
class ExternalChannelAccessService:
    """Apply authenticated approver decisions without provider network calls."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    agent_repository: Annotated[
        AgentRepository,
        Depends(AgentRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    input_buffer_service: Annotated[
        InputBufferService,
        Depends(InputBufferService),
    ]
    session_lifecycle: Annotated[
        SessionLifecycleService,
        Depends(SessionLifecycleService),
    ]

    async def allow(
        self,
        *,
        access_request_id: str,
        scope: ExternalChannelAccessGrantScope,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelAllowedAccess:
        """Allow one participant and create its Session binding atomically."""
        wake_required = False
        wake_session_id: str | None = None
        wake_agent_id: str | None = None
        async with self.session_manager() as session:
            request_snapshot = await self.repository.get_access_request(
                session,
                access_request_id=access_request_id,
            )
            if request_snapshot is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=request_snapshot.route_id,
            )
            if route is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            binding = await self.repository.lock_active_binding_by_route_resource(
                session,
                route_id=request_snapshot.route_id,
                resource_id=request_snapshot.resource_id,
            )
            resource = await self.repository.lock_resource(
                session,
                resource_id=request_snapshot.resource_id,
            )
            request = await self._locked_request(
                session,
                access_request_id=access_request_id,
            )
            if request.status is ExternalChannelAccessRequestStatus.ALLOWED:
                grant = await self.repository.get_active_access_grant(
                    session,
                    agent_id=route.agent_id,
                    principal_id=request.principal_id,
                    agent_session_id=request.agent_session_id,
                )
                if binding is None or grant is None or grant.scope is not scope:
                    raise ExternalChannelAccessDecisionError(
                        "The prior Allow decision no longer has its active state."
                    )
                if (
                    binding.activation_status
                    is ExternalChannelBindingActivationStatus.ACTIVE
                ):
                    wake_required = await self._release_allowed_request(
                        session,
                        binding=binding,
                        trigger_message_id=request.source_message_id,
                        now=now,
                    )
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=request.id,
                    )
                )
                await session.commit()
                if wake_required:
                    await self._send_session_wake_up(
                        agent_id=route.agent_id,
                        session_id=binding.agent_session_id,
                    )
                return ExternalChannelAllowedAccess(
                    request=request,
                    binding=binding,
                    grant=grant,
                    control_delete_delivery_id=(
                        None if delete_intent is None else delete_intent.id
                    ),
                )
            self._require_pending(request, now=now)
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise ExternalChannelAccessDecisionError(
                    "The external conversation is not active."
                )
            agent = await self.agent_repository.get_by_id(session, route.agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise ExternalChannelAccessDecisionError("The Agent is not active.")
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent.id,
                    principal_id=request.principal_id,
                )
                is not None
            ):
                raise ExternalChannelAccessDecisionError(
                    "The external participant is blocked."
                )

            if binding is not None:
                agent_session_id = binding.agent_session_id
            elif request.agent_session_id is not None:
                raise ExternalChannelAccessDecisionError(
                    "The linked External Channel binding is no longer active."
                )
            else:
                agent_session = await self.agent_session_repository.create(
                    session,
                    AgentSessionCreate(
                        workspace_id=agent.workspace_id,
                        agent_id=agent.id,
                        title=None,
                        start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
                    ),
                )
                agent_session_id = agent_session.id
            snapshot_count = request.decision_policy_snapshot.get(
                "pending_truncation_message_count",
                0,
            )
            snapshot_size = request.decision_policy_snapshot.get(
                "pending_truncation_size",
                0,
            )
            binding = await self.repository.create_binding_idempotent(
                session,
                ExternalChannelBindingCreate(
                    resource_id=request.resource_id,
                    route_id=request.route_id,
                    agent_session_id=agent_session_id,
                    status=ExternalChannelBindingStatus.ACTIVE,
                    activation_status=(
                        ExternalChannelBindingActivationStatus.WAITING_HYDRATION
                    ),
                    activation_trigger_message_id=request.source_message_id,
                    activated_at=None,
                    projected_through_position=None,
                    truncated_message_count=(
                        snapshot_count if isinstance(snapshot_count, int) else 0
                    ),
                    truncated_size=(
                        snapshot_size if isinstance(snapshot_size, int) else 0
                    ),
                    disconnected_at=None,
                    disconnect_reason=None,
                ),
            )
            grant = await self.repository.ensure_access_grant(
                session,
                ExternalChannelAccessGrantCreate(
                    agent_id=agent.id,
                    principal_id=request.principal_id,
                    scope=scope,
                    agent_session_id=(
                        agent_session_id
                        if scope is ExternalChannelAccessGrantScope.SESSION
                        else None
                    ),
                    granted_by_user_id=decided_by_user_id,
                    source_access_request_id=request.id,
                    revoked_by_user_id=None,
                    revoked_at=None,
                ),
            )
            decided = await self.repository.decide_access_request(
                session,
                access_request_id=request.id,
                status=ExternalChannelAccessRequestStatus.ALLOWED,
                agent_session_id=agent_session_id,
                decided_by_user_id=decided_by_user_id,
                decision_summary=decision_summary,
                decided_at=now,
            )
            if decided is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            if (
                binding.activation_status
                is ExternalChannelBindingActivationStatus.ACTIVE
            ):
                wake_required = await self._release_allowed_request(
                    session,
                    binding=binding,
                    trigger_message_id=request.source_message_id,
                    now=now,
                )
                wake_session_id = binding.agent_session_id
                wake_agent_id = route.agent_id
            delete_intent = (
                await self.repository.create_access_request_control_delete_intent(
                    session,
                    access_request_id=request.id,
                )
            )
            await session.commit()
            if (
                wake_required
                and wake_session_id is not None
                and wake_agent_id is not None
            ):
                await self._send_session_wake_up(
                    agent_id=wake_agent_id,
                    session_id=wake_session_id,
                )
            return ExternalChannelAllowedAccess(
                request=decided,
                binding=binding,
                grant=grant,
                control_delete_delivery_id=(
                    None if delete_intent is None else delete_intent.id
                ),
            )

    async def _release_allowed_request(
        self,
        session: AsyncSession,
        *,
        binding: ExternalChannelBinding,
        trigger_message_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Create the approved invocation on an already-active binding."""
        existing = await self.repository.get_invocation_batch(
            session,
            binding_id=binding.id,
            trigger_message_id=trigger_message_id,
        )
        if existing is not None and existing.input_buffer_id is not None:
            return True
        trigger = await self.repository.get_message(
            session,
            message_id=trigger_message_id,
        )
        if trigger is None or trigger.current_revision_id is None:
            raise ExternalChannelAccessDecisionError(
                "The approved external message is unavailable."
            )
        pending = await self.repository.list_pending_context(
            session,
            route_id=binding.route_id,
            resource_id=binding.resource_id,
            now=now,
            through_provider_position=trigger.provider_position,
        )
        items = [(item.message_revision_id, item.provider_position) for item in pending]
        if all(revision_id != trigger.current_revision_id for revision_id, _ in items):
            items.append((trigger.current_revision_id, trigger.provider_position))
        items.sort(key=lambda item: item[1])
        batch = await self.repository.create_invocation_batch_idempotent(
            session,
            ExternalChannelInvocationBatchCreate(
                binding_id=binding.id,
                trigger_message_id=trigger_message_id,
                first_provider_position=items[0][1],
                last_provider_position=items[-1][1],
                truncation_message_count=binding.truncated_message_count,
                truncation_size=binding.truncated_size,
                input_buffer_id=None,
            ),
        )
        for sequence, (revision_id, provider_position) in enumerate(items):
            await self.repository.create_invocation_batch_item_idempotent(
                session,
                ExternalChannelInvocationBatchItemCreate(
                    batch_id=batch.id,
                    message_revision_id=revision_id,
                    sequence=sequence,
                    provider_position=provider_position,
                ),
            )
        locked_batch = await self.repository.lock_invocation_batch(
            session,
            batch_id=batch.id,
        )
        if locked_batch is None:
            raise ExternalChannelAccessDecisionError(
                "The invocation batch disappeared during activation."
            )
        if locked_batch.input_buffer_id is None:
            enqueue = await self.input_buffer_service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=binding.agent_session_id,
                    kind=InputBufferKind.EXTERNAL_CHANNEL_INVOCATION,
                    scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    actor_user_id=None,
                    content="",
                    idempotency_key=f"external-channel-invocation:{batch.id}",
                    metadata={
                        EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY: batch.id
                    },
                    attachments=[],
                    file_parts=[],
                    action=None,
                ),
            )
            await self.repository.link_invocation_batch_input_buffer(
                session,
                batch_id=batch.id,
                input_buffer_id=enqueue.input_buffer.id,
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                binding.agent_session_id,
            )
        await self.repository.delete_pending_context_ids(
            session,
            pending_context_ids=[item.id for item in pending],
        )
        await self.repository.advance_binding_projection(
            session,
            binding_id=binding.id,
            projected_through_position=items[-1][1],
        )
        return True

    async def _send_session_wake_up(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Send an idempotent post-commit wake for one released invocation."""
        await self.session_lifecycle.send_session_wake_up(
            SessionWakeUp(
                agent_id=agent_id,
                session_id=session_id,
                user_id=None,
                additional_system_prompt=None,
                interface=None,
                workspace_id=None,
                workspace_handle=None,
            )
        )

    async def deny(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Resolve only the source access request as denied."""
        return await self._resolve(
            access_request_id=access_request_id,
            action="deny",
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def block(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Create the Agent-level block and resolve the source request."""
        return await self._resolve(
            access_request_id=access_request_id,
            action="block",
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def revoke_grant(
        self,
        *,
        grant_id: str,
    ) -> ExternalChannelRevokedAccess:
        """Revoke one Session- or Agent-scoped participant grant."""
        async with self.session_manager() as session:
            grant = await self.repository.delete_access_grant(
                session,
                grant_id=grant_id,
            )
            if grant is None:
                raise ExternalChannelAccessDecisionError(
                    "The access grant does not exist."
                )
            await session.commit()
            return ExternalChannelRevokedAccess(grant=grant)

    async def remove_block(
        self,
        *,
        block_id: str,
        removed_by_user_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelRemovedBlock:
        """Remove one Agent-level participant block."""
        async with self.session_manager() as session:
            block = await self.repository.remove_block(
                session,
                block_id=block_id,
                removed_by_user_id=removed_by_user_id,
                removed_at=now,
            )
            if block is None:
                raise ExternalChannelAccessDecisionError(
                    "The access block does not exist."
                )
            await session.commit()
            return ExternalChannelRemovedBlock(block=block)

    async def _resolve(
        self,
        *,
        access_request_id: str,
        action: Literal["deny", "block"],
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        async with self.session_manager() as session:
            request = await self._locked_request(
                session,
                access_request_id=access_request_id,
            )
            expected_status = (
                ExternalChannelAccessRequestStatus.BLOCKED
                if action == "block"
                else ExternalChannelAccessRequestStatus.DENIED
            )
            if request.status is expected_status:
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=request.id,
                    )
                )
                await session.commit()
                return ExternalChannelResolvedAccess(
                    request=request,
                    control_delete_delivery_id=(
                        None if delete_intent is None else delete_intent.id
                    ),
                )
            self._require_pending(request, now=now)
            route = await self.repository.get_agent_route(
                session,
                route_id=request.route_id,
            )
            if route is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route does not exist."
                )
            if action == "block":
                await self.repository.create_block_idempotent(
                    session,
                    ExternalChannelBlockCreate(
                        agent_id=route.agent_id,
                        principal_id=request.principal_id,
                        blocked_by_user_id=decided_by_user_id,
                        reason=decision_summary,
                        removed_by_user_id=None,
                        removed_at=None,
                    ),
                )
            decided = await self.repository.decide_access_request(
                session,
                access_request_id=request.id,
                status=expected_status,
                agent_session_id=request.agent_session_id,
                decided_by_user_id=decided_by_user_id,
                decision_summary=decision_summary,
                decided_at=now,
            )
            if decided is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            delete_intent = (
                await self.repository.create_access_request_control_delete_intent(
                    session,
                    access_request_id=request.id,
                )
            )
            await session.commit()
            return ExternalChannelResolvedAccess(
                request=decided,
                control_delete_delivery_id=(
                    None if delete_intent is None else delete_intent.id
                ),
            )

    async def _locked_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ExternalChannelAccessRequest:
        request = await self.repository.lock_access_request(
            session,
            access_request_id=access_request_id,
        )
        if request is None:
            raise ExternalChannelAccessRequestNotFound(access_request_id)
        return request

    @staticmethod
    def _require_pending(
        request: ExternalChannelAccessRequest,
        *,
        now: datetime.datetime,
    ) -> None:
        if request.status is not ExternalChannelAccessRequestStatus.PENDING:
            raise ExternalChannelAccessDecisionError(
                "The access request has already been resolved."
            )
        if request.expires_at <= now:
            raise ExternalChannelAccessDecisionError("The access request has expired.")
